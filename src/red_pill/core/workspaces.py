"""
Workspace Registry — red-pill multi-project support.

red-pill is the AGENT (identity + Bünker + a GLOBAL Agent_Core desk). On top of it the operator
works in N independent PROJECT workspaces (peers) — e.g. a legacy monolith and a new-architecture
monorepo, with no parent/child relationship. This registry lists those workspaces; each project's
rules/standards are discovered at runtime via the `.agent` convention (a dir or symlink at/above the
workspace root), never hardcoded.

Config lives at XDG `~/.config/red-pill/workspaces.yaml` (template in examples/workspaces.yaml). If
absent, a back-compat registry is derived (agent_core from config, no project workspaces).

This is ORTHOGONAL to `config.WORKSPACE_ROOT` (which is red-pill's own ecosystem/asset root, infra).
"""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

from red_pill.core.paths import get_agent_dir, get_config_dir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Workspace:
	name: str
	root: Path
	atlas: Optional[Path] = None   # hook (permissions step): explicit per-workspace standards path
	graphify: bool = False         # hook (graphify timer step): index this workspace's AST


@dataclass(frozen=True)
class WorkspaceRegistry:
	agent_core: Path
	workspaces: List[Workspace] = field(default_factory=list)

	def get(self, name: str) -> Optional[Workspace]:
		return next((w for w in self.workspaces if w.name == name), None)


def _expand(value) -> Path:
	return Path(os.path.expanduser(str(value)))


def registry_path() -> Path:
	"""XDG config location for the workspace registry."""
	return get_config_dir() / "workspaces.yaml"


def _back_compat_registry() -> WorkspaceRegistry:
	"""No registry on disk yet: agent_core from existing config, no project workspaces (safe empty)."""
	agent_core = "~/Agent_Core"
	try:
		import red_pill.config as cfg  # lazy: avoid import cycle (config does not import this module)

		agent_core = getattr(cfg, "AGENT_CORE_DIR", None) or agent_core
	except Exception as exc:  # pragma: no cover - defensive
		logger.debug("[workspaces] config unavailable for back-compat: %s", exc)
	return WorkspaceRegistry(agent_core=_expand(agent_core), workspaces=[])


def load_registry() -> WorkspaceRegistry:
	"""Load the workspace registry, or derive a back-compat one if absent/unreadable."""
	path = registry_path()
	if not path.exists():
		logger.info("[workspaces] no registry at %s — back-compat (agent_core only)", path)
		return _back_compat_registry()
	try:
		with open(path, encoding="utf-8") as f:
			raw = yaml.safe_load(f) or {}
	except Exception as exc:
		logger.error("[workspaces] failed to parse %s: %s — using back-compat", path, exc)
		return _back_compat_registry()

	agent_core = _expand(raw.get("agent_core") or _back_compat_registry().agent_core)
	workspaces: List[Workspace] = []
	for entry in raw.get("workspaces") or []:
		try:
			workspaces.append(
				Workspace(
					name=entry["name"],
					root=_expand(entry["root"]),
					atlas=_expand(entry["atlas"]) if entry.get("atlas") else None,
					graphify=bool(entry.get("graphify", False)),
				)
			)
		except Exception as exc:
			logger.warning("[workspaces] skipping malformed workspace entry %r: %s", entry, exc)
	return WorkspaceRegistry(agent_core=agent_core, workspaces=workspaces)


def agent_core_dir() -> Path:
	"""The agent's GLOBAL personal desk (transversal)."""
	return load_registry().agent_core


def list_workspaces() -> List[Workspace]:
	return load_registry().workspaces


def find_closest_agent(start) -> Path:
	"""Walk up from `start` to the nearest `.agent` (dir or symlink). Caps at $HOME.
	Fallback: get_agent_dir() (~/.agent). Never raises — degrades on bad symlinks/perms."""
	home = Path.home()
	try:
		cur = _expand(start).resolve()
	except Exception:
		cur = _expand(start)
	if cur.is_file():
		cur = cur.parent

	while True:
		candidate = cur / ".agent"
		try:
			if candidate.is_dir() or candidate.is_symlink():
				return candidate
		except OSError:
			pass
		if cur == cur.parent or cur == home:
			break
		cur = cur.parent
	return get_agent_dir()


def resolve_standards(ws: Workspace) -> Path:
	"""Standards/rules location for a workspace: its explicit `atlas`, else its nearest `.agent`
	(symlink followed to the real target if it resolves)."""
	if ws.atlas:
		return ws.atlas
	agent = find_closest_agent(ws.root)
	try:
		return agent.resolve()
	except Exception:
		return agent
