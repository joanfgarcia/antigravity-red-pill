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
from pathlib import Path
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from red_pill.core.paths import get_agent_dir, get_config_dir

logger = logging.getLogger(__name__)


class Workspace(BaseModel):
	"""A single PROJECT workspace entry. Pydantic-validated: paths are ~-expanded,
	`name` must be non-empty, flags are coerced to bool. Frozen (immutable) — mutate
	via `model_copy(update=...)`."""

	model_config = ConfigDict(frozen=True)

	name: str
	root: Path
	atlas: Optional[Path] = None  # hook (permissions step): explicit per-workspace standards path
	graphify: bool = False  # hook (graphify timer step): index this workspace's AST
	access: bool = False  # operator opt-in: grant FS access (additionalDirectories) to this workspace
	memory: Union[bool, Path] = False  # memory serving: true/false or custom path (e.g. true => root/.red-pill/memory/)

	@field_validator("name")
	@classmethod
	def _name_nonempty(cls, v: str) -> str:
		if not str(v).strip():
			raise ValueError("workspace name must be non-empty")
		return v

	@field_validator("root", "atlas", mode="before")
	@classmethod
	def _expand_paths(cls, v):
		# Empty/None atlas → None; otherwise ~-expand. A missing `root` then fails
		# validation (required), which is the point — malformed entries are rejected.
		if v in (None, ""):
			return None
		return _expand(v)

	@field_validator("memory", mode="before")
	@classmethod
	def _expand_memory(cls, v):
		if v in (None, ""):
			return False
		if isinstance(v, str):
			v_lower = v.strip().lower()
			if v_lower in ("true", "yes", "on"):
				return True
			if v_lower in ("false", "no", "off"):
				return False
			return _expand(v)
		return v

	@property
	def get_memory_path(self) -> Optional[Path]:
		if not self.memory:
			return None
		if isinstance(self.memory, bool):
			return self.root / ".red-pill" / "memory"
		path = Path(self.memory)
		if path.is_absolute():
			return path
		return (self.root / path).resolve()


class WorkspaceRegistry(BaseModel):
	"""The full registry: the agent's GLOBAL desk + the list of peer workspaces."""

	model_config = ConfigDict(frozen=True)

	agent_core: Path
	workspaces: List[Workspace] = Field(default_factory=list)
	version: int = 1

	@field_validator("agent_core", mode="before")
	@classmethod
	def _expand_agent_core(cls, v):
		return _expand(v)

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

	agent_core = raw.get("agent_core") or _back_compat_registry().agent_core
	workspaces: List[Workspace] = []
	for entry in raw.get("workspaces") or []:
		try:
			workspaces.append(Workspace.model_validate(entry))
		except Exception as exc:
			logger.warning("[workspaces] skipping malformed workspace entry %r: %s", entry, exc)
	try:
		return WorkspaceRegistry(agent_core=agent_core, workspaces=workspaces, version=int(raw.get("version", 1)))
	except Exception as exc:
		logger.error("[workspaces] invalid registry %s: %s — using back-compat", path, exc)
		return _back_compat_registry()


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


# ── Registry writes (used by `red-pill workspace` / scripts/manage_workspaces.py) ──
_REGISTRY_HEADER = """\
# Workspace registry for red-pill — PROJECT workspaces (peers).
# Managed by `red-pill workspace` (scripts/manage_workspaces.py); hand-editable too.
#
# agent_core = the agent's GLOBAL personal desk (transversal, shared across ALL workspaces).
# Each workspace's rules/standards are discovered at runtime via the `.agent` convention.
# Per-workspace fields:
#   root     : the project repo root.
#   atlas    : optional explicit standards path (null = auto-discover via .agent).
#   graphify : whether the AST-refresh timer indexes this workspace.
#   access   : operator opt-in — grant the agent filesystem access (additionalDirectories).
#              false = in AUTONOMOUS mode the agent CANNOT operate in this workspace.
#   memory   : true/false or custom memory path (e.g. true => root/.red-pill/memory/)
"""


def _to_tilde(p) -> str:
	"""Render a path with $HOME collapsed to ~ for a tidy, portable registry file."""
	home = str(Path.home())
	s = str(p)
	return "~" + s[len(home) :] if s == home or s.startswith(home + os.sep) else s


def serialize_registry(registry: WorkspaceRegistry) -> str:
	"""Pure serialization (no I/O) — testable. Regenerates the documented header; PyYAML-style
	inline comments are not preserved (we re-emit the header instead)."""
	lines = [_REGISTRY_HEADER, f"version: {registry.version}", f'agent_core: "{_to_tilde(registry.agent_core)}"']
	if not registry.workspaces:
		lines.append("workspaces: []")
	else:
		lines.append("workspaces:")
		for w in registry.workspaces:
			atlas = f'"{_to_tilde(w.atlas)}"' if w.atlas else "null"
			if isinstance(w.memory, bool):
				memory_val = str(w.memory).lower()
			elif w.memory:
				memory_val = f'"{_to_tilde(w.memory)}"'
			else:
				memory_val = "false"
			lines.append(
				f'  - {{ name: {w.name}, root: "{_to_tilde(w.root)}", atlas: {atlas}, '
				f"graphify: {str(w.graphify).lower()}, access: {str(w.access).lower()}, "
				f"memory: {memory_val} }}"
			)
	return "\n".join(lines) + "\n"


def save_registry(registry: WorkspaceRegistry) -> Path:
	"""Persist the registry to its XDG path."""
	path = registry_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(serialize_registry(registry), encoding="utf-8")
	return path


def _match(registry: WorkspaceRegistry, name_or_path: str) -> Optional[Workspace]:
	"""Find a workspace by exact name, else by resolved root path."""
	found = registry.get(name_or_path)
	if found:
		return found
	try:
		target = _expand(name_or_path).resolve()
	except Exception:
		target = _expand(name_or_path)
	for ws in registry.workspaces:
		try:
			if ws.root.resolve() == target:
				return ws
		except Exception:
			if ws.root == target:
				return ws
	return None


def find_workspace(name_or_path: str) -> Optional[Workspace]:
	"""Public lookup by name or root path against the on-disk registry."""
	return _match(load_registry(), name_or_path)


def add_or_enable_workspace(path, name: Optional[str] = None):
	"""Register `path` (if new) with access=True, or flip an existing entry to access=True.
	Returns (registry, workspace, was_new). Minimal by design: new entries default
	atlas=None (auto-discovered via .agent) and graphify=False."""
	registry = load_registry()
	root = _expand(path)
	existing = _match(registry, str(root))
	if existing:
		updated = existing.model_copy(update={"access": True})
		workspaces = [updated if w.name == existing.name else w for w in registry.workspaces]
		ws_out, was_new = updated, False
	else:
		ws_out = Workspace(name=name or root.name, root=root, atlas=None, graphify=False, access=True)
		workspaces = list(registry.workspaces) + [ws_out]
		was_new = True
	registry = WorkspaceRegistry(agent_core=registry.agent_core, workspaces=workspaces, version=registry.version)
	save_registry(registry)
	return registry, ws_out, was_new


def set_access(name_or_path: str, value: bool) -> Optional[Workspace]:
	"""Flip a workspace's access flag. Returns the updated workspace, or None if not found."""
	registry = load_registry()
	target = _match(registry, name_or_path)
	if not target:
		return None
	updated = target.model_copy(update={"access": value})
	workspaces = [updated if w.name == target.name else w for w in registry.workspaces]
	save_registry(WorkspaceRegistry(agent_core=registry.agent_core, workspaces=workspaces, version=registry.version))
	return updated


def remove_workspace(name_or_path: str) -> Optional[Workspace]:
	"""Delete a workspace entry entirely. Returns the removed workspace, or None if not found."""
	registry = load_registry()
	target = _match(registry, name_or_path)
	if not target:
		return None
	workspaces = [w for w in registry.workspaces if w.name != target.name]
	save_registry(WorkspaceRegistry(agent_core=registry.agent_core, workspaces=workspaces, version=registry.version))
	return target
