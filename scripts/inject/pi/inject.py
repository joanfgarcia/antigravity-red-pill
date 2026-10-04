"""Inject red-pill configuration into Pi (pi-coding-agent).

The Búnker bridge is a TS extension (`seeds/pi/extensions/red-pill.ts`). Its
per-turn RAG talks to the RedPill-Kernel MCP server (`bunker_memory_api` action
`recall`) over a persistent stdio connection using `@earendil-works/pi-mcp`; the
injector provisions that client under `<pi_dir>/node_modules` (Pi does not put
it on an extension's resolution path). Identity (wake_up_v6) and the on-demand
tools still use the red-pill CLI via `uv run`. Skills are copied into
`~/.pi/agent/skills/` (single merged dir: generic `skills/` first, then
`seeds/pi/skills/` overrides win), which Pi auto-discovers. Legacy snake_case
skill dirs (renamed to kebab-case 2026-09-10) are pruned so a reseed converges
and is idempotent.

The anchor is spliced into `<workspace>/AGENTS.override.md`: since Pi 0.87 that
file REPLACES `AGENTS.md`/`CLAUDE.md` from the same directory, so it shadows the
claude-code-project anchor (which speaks MCP) with Pi-specific text. Seeds come
from `seeds/pi/anchors/` (override) falling back to `seeds/anchors/` (generic).

Never touches `~/.pi/agent/settings.json` (provider/models belong to the
operator). The extension owns its own MCP connection; the injector never
configures `~/.pi/agent/mcp.json`.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

logger = logging.getLogger("inject_pi")

sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "..")))
from _config_common import LEGACY_SKILL_DIRS, agent_core_vars, build_vars, subst  # noqa: E402

ANCHORS = ["sovereign_handshake", "agent_core", "knowledge_access", "frontmatter_docs", "job_dag_execution"]


def _pi_agent_dir() -> str:
	return os.path.expanduser("~/.pi/agent")


def _workspace_root(args) -> str | None:
	"""Workspace root for the Pi anchor override: --workspace → WORKSPACE_ROOT (.env) → None."""
	ws = getattr(args, "workspace", None)
	if ws:
		return os.path.abspath(os.path.expanduser(ws))
	home = os.path.expanduser("~")
	root = os.environ.get("WORKSPACE_ROOT")
	if not root:
		env_path = os.path.join(home, ".config", "red-pill", ".env")
		if os.path.exists(env_path):
			with open(env_path, encoding="utf-8") as f:
				for raw in f:
					line = raw.strip()
					if line.startswith("WORKSPACE_ROOT="):
						root = line.partition("=")[2].strip().strip('"').strip("'")
						break
	if root:
		return os.path.expanduser(root.replace("${HOME}", home))
	return None


def _seed_anchor(repo_root: str, args, backup: bool, remove: bool = False) -> int:
	"""Splice red-pill anchors into <workspace>/AGENTS.override.md (Pi shadows CLAUDE.md).

	Pi >=0.87 loads AGENTS.override.md INSTEAD of AGENTS.md/CLAUDE.md from that
	directory, so this shadows the claude-code-project anchor (which speaks MCP)
	with Pi-specific text (automatic handshake, bunker_search/bunker_save).
	"""
	workspace = _workspace_root(args)
	if not workspace:
		logger.warning("· Pi anchor omitido: sin --workspace ni WORKSPACE_ROOT (.env)")
		return 0
	scripts_dir = os.path.join(repo_root, "scripts")
	if scripts_dir not in sys.path:
		sys.path.insert(0, scripts_dir)
	import inject_anchor  # noqa: E402

	variables = build_vars(argparse.Namespace(redpill_dir=repo_root, uv_path=getattr(args, "uv_path", None), workspace=workspace))
	variables.update(agent_core_vars())
	seeds_dir = os.path.join(repo_root, "seeds", "anchors")
	return inject_anchor.splice_ide("pi", ANCHORS, seeds_dir, workspace, variables, backup=backup, remove=remove)


def _read_seed(path: str) -> str:
	with open(path, encoding="utf-8") as f:
		return f.read()


def _overridden_files(override_dir: str) -> set:
	"""Set of (skill, relpath) covered by an IDE-specific override dir.

	Used to SKIP those files in the generic pass: if the generic copy ran first
	and the override after, the next generic pass would see a diff and rewrite
	the override's file, so the reseed would never converge."""
	out: set = set()
	if not os.path.isdir(override_dir):
		return out
	for skill in os.listdir(override_dir):
		skill_dir = os.path.join(override_dir, skill)
		if not os.path.isdir(skill_dir):
			continue
		for root, _dirs, files in os.walk(skill_dir):
			for name in files:
				out.add((skill, os.path.relpath(os.path.join(root, name), skill_dir)))
	return out


def _deploy_skills(src_dir: str, dest_dir: str, variables: dict, backup: bool, skip: set | None = None) -> int:
	"""Copy a skills dir into the Pi skills root. Returns number of changed skills."""
	changed = 0
	if not os.path.isdir(src_dir):
		return 0
	os.makedirs(dest_dir, exist_ok=True)
	for skill_entry in sorted(os.listdir(src_dir)):
		skill_src = os.path.join(src_dir, skill_entry)
		skill_md = os.path.join(skill_src, "SKILL.md")
		if not os.path.isdir(skill_src) or not os.path.exists(skill_md):
			continue
		skill_dest_dir = os.path.join(dest_dir, skill_entry)
		os.makedirs(skill_dest_dir, exist_ok=True)
		skill_changed = 0
		for root, dirs, files in os.walk(skill_src):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			rel_root = os.path.relpath(root, skill_src)
			dest_root = skill_dest_dir if rel_root == "." else os.path.join(skill_dest_dir, rel_root)
			os.makedirs(dest_root, exist_ok=True)
			for name in files:
				src_file = os.path.join(root, name)
				if skip and (skill_entry, os.path.relpath(src_file, skill_src)) in skip:
					continue  # lo pisa un override específico-IDE
				dest_file = os.path.join(dest_root, name)
				if name.endswith(".md"):
					resolved = subst(_read_seed(src_file), variables)
					if os.path.exists(dest_file):
						with open(dest_file, encoding="utf-8") as f:
							if f.read() == resolved:
								continue
						if backup:
							shutil.copy2(dest_file, dest_file + ".bak")
					with open(dest_file, "w", encoding="utf-8") as f:
						f.write(resolved)
				else:
					if os.path.exists(dest_file):
						with open(dest_file, "rb") as a, open(src_file, "rb") as b:
							if a.read() == b.read():
								continue
						if backup:
							shutil.copy2(dest_file, dest_file + ".bak")
					shutil.copy2(src_file, dest_file)
				skill_changed += 1
		if skill_changed:
			changed += 1
			logger.info(f"✓ Pi skill '{skill_entry}' deployed → {skill_dest_dir}")
		else:
			logger.info(f"· Pi skill '{skill_entry}' sin cambios")
	return changed


def _prune_legacy(skills_dest: str) -> int:
	"""Remove pre-rename snake_case skill dirs. Returns number removed."""
	removed = 0
	for legacy in LEGACY_SKILL_DIRS:
		path = os.path.join(skills_dest, legacy)
		if os.path.isdir(path):
			shutil.rmtree(path)
			logger.info(f"✓ Pi legacy skill '{legacy}' removed")
			removed += 1
	return removed


def _deploy_extension(pi_dir: str, seed: str, variables: dict, backup: bool) -> int:
	extensions_dir = os.path.join(pi_dir, "extensions")
	os.makedirs(extensions_dir, exist_ok=True)
	dest = os.path.join(extensions_dir, "red-pill.ts")
	resolved = subst(_read_seed(seed), variables)
	if os.path.exists(dest):
		with open(dest, encoding="utf-8") as f:
			if f.read() == resolved:
				logger.info("· Pi extension 'red-pill.ts' sin cambios")
				return 0
		if backup:
			shutil.copy2(dest, dest + ".bak")
	with open(dest, "w", encoding="utf-8") as f:
		f.write(resolved)
	logger.info(f"✓ Pi extension deployed → {dest}")
	return 1


# `@earendil-works/pi-mcp` is the standalone MCP client published with Pi. It is
# not on an extension's module resolution path, so we provision it into the
# agent dir. Pinned to Pi's own version for wire-protocol compatibility.
PI_MCP_PACKAGE = "@earendil-works/pi-mcp"
PI_MCP_FALLBACK_VERSION = "1.0.2"


def _pi_mcp_version() -> str:
	"""Target pi-mcp version = the running Pi version (best effort)."""
	import re
	import subprocess

	for cmd in (["pi", "--version"], ["pi", "-v"]):
		try:
			out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
			match = re.match(r"(\d+\.\d+\.\d+)", (out.stdout or "").strip())
			if match:
				return match.group(1)
		except Exception:
			continue
	return PI_MCP_FALLBACK_VERSION


def _ensure_pi_mcp_client(pi_dir: str) -> int:
	"""Provision @earendil-works/pi-mcp into <pi_dir>/node_modules so the
	extension can `import { McpClient }`. Best-effort and idempotent: skips when
	it already exists or when npm is unavailable (logs a warning). Returns the
	number of changes."""
	import subprocess

	pkg_dir = os.path.join(pi_dir, "node_modules", "@earendil-works", "pi-mcp")
	if os.path.isdir(pkg_dir):
		logger.info("· pi-mcp client ya provisionado")
		return 0
	npm = shutil.which("npm")
	if not npm:
		logger.warning(f"⚠ npm no encontrado: la extensión Pi necesita {PI_MCP_PACKAGE}. Instálalo a mano en {pi_dir}")
		return 0
	spec = f"{PI_MCP_PACKAGE}@{_pi_mcp_version()}"
	try:
		result = subprocess.run([npm, "install", "--prefix", pi_dir, "--no-save", spec], capture_output=True, text=True, timeout=300)
	except Exception as exc:
		logger.warning(f"⚠ No se pudo provisionar {spec}: {exc}")
		return 0
	if result.returncode != 0:
		logger.warning(f"⚠ npm install {spec} falló: {(result.stderr or '').strip()[:200]}")
		return 0
	logger.info(f"✓ pi-mcp client provisionado → {pkg_dir} ({spec})")
	return 1


def _remove(pi_dir: str, repo_root: str, args) -> int:
	removed = 0
	ext = os.path.join(pi_dir, "extensions", "red-pill.ts")
	if os.path.exists(ext):
		os.remove(ext)
		removed += 1
		logger.info("✓ Pi extension 'red-pill.ts' removed")
	skills_dest = os.path.join(pi_dir, "skills")
	managed = list(LEGACY_SKILL_DIRS)
	for src in (os.path.join(repo_root, "skills"), os.path.join(repo_root, "seeds", "pi", "skills")):
		if os.path.isdir(src):
			for entry in os.listdir(src):
				if os.path.exists(os.path.join(src, entry, "SKILL.md")):
					managed.append(entry)
	for name in sorted(set(managed)):
		path = os.path.join(skills_dest, name)
		if os.path.isdir(path):
			shutil.rmtree(path)
			removed += 1
			logger.info(f"✓ Pi skill '{name}' removed")
	removed += _seed_anchor(repo_root, args, backup=False, remove=True)
	return removed


def inject(args: argparse.Namespace) -> int:
	pi_dir = _pi_agent_dir()
	if not os.path.isdir(pi_dir):
		os.makedirs(pi_dir, exist_ok=True)

	script_dir = os.path.dirname(os.path.abspath(__file__))
	# scripts/inject/pi/ → scripts/ → repo root
	repo_root = os.path.normpath(os.path.join(script_dir, "..", "..", ".."))
	if not getattr(args, "redpill_dir", None):
		args.redpill_dir = repo_root  # RED_PILL_DIR / RED_PILL_CMD necesitan el checkout

	variables = build_vars(args)
	backup = not getattr(args, "no_backup", False)

	if getattr(args, "remove", False):
		return _remove(pi_dir, repo_root, args)

	changed = 0
	# 1. Extension
	seed_ext = os.path.join(repo_root, "seeds", "pi", "extensions", "red-pill.ts")
	if os.path.exists(seed_ext):
		changed += _deploy_extension(pi_dir, seed_ext, variables, backup)
		changed += _ensure_pi_mcp_client(pi_dir)

	# 2. Skills: genérico primero, override específico-IDE después (gana).
	#    Los ficheros pisados por el override se SALTAN en la pasada genérica
	#    (si no, la genérica los re-copia y el reseed no converge).
	skills_dest = os.path.join(pi_dir, "skills")
	pi_skills_src = os.path.join(repo_root, "seeds", "pi", "skills")
	changed += _deploy_skills(os.path.join(repo_root, "skills"), skills_dest, variables, backup, skip=_overridden_files(pi_skills_src))
	changed += _deploy_skills(pi_skills_src, skills_dest, variables, backup)
	# 3. Prune legados snake_case → reseed convergente e idempotente.
	changed += _prune_legacy(skills_dest)

	# 4. Anchor → <workspace>/AGENTS.override.md (shadows CLAUDE.md for Pi, which
	#    carries the claude-code MCP anchor). Pi-specific seed overrides win.
	changed += _seed_anchor(repo_root, args, backup, remove=False)

	return changed
