"""Shared placeholder resolution for the red-pill config injectors.

Imported by both ``inject_mcp.py`` and ``inject_anchor.py``. Kept standalone
(no ``red_pill`` package import) so the MCP injector stays dependency-free.
"""

import os
import shutil


# ── Placeholder resolution for manifest / anchor definitions ──────────────────
def build_vars(args):
	npx = shutil.which("npx")
	claude = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
	return {
		"HOME": os.path.expanduser("~"),
		"UV": getattr(args, "uv_path", None) or shutil.which("uv") or os.path.expanduser("~/.local/bin/uv"),
		"NPX": npx or "",
		"NPX_DIR": os.path.dirname(npx) if npx else "",
		"CLAUDE_CLI": claude,
		"GRAPHIFY_PY": os.path.expanduser("~/.local/share/uv/tools/graphifyy/bin/python3"),
		"REDPILL_DIR": getattr(args, "redpill_dir", None) or "",
		"WORKSPACE": os.path.expanduser(args.workspace) if getattr(args, "workspace", None) else "",
	}


def subst(value, variables):
	if isinstance(value, str):
		for key, val in variables.items():
			value = value.replace("${%s}" % key, val)
		return value
	if isinstance(value, list):
		return [subst(item, variables) for item in value]
	if isinstance(value, dict):
		return {key: subst(item, variables) for key, item in value.items()}
	return value


# ── Agent_Core / transversal vars (red-pill .env, with fallbacks) ─────────────
def parse_env_file(path):
	vals = {}
	if not os.path.exists(path):
		return vals
	with open(path, encoding="utf-8") as f:
		for raw in f:
			line = raw.strip()
			if not line or line.startswith("#") or "=" not in line:
				continue
			key, _, val = line.partition("=")
			vals[key.strip()] = val.strip().strip('"').strip("'")
	return vals


def _agent_core_from_registry(home):
	"""agent_core from the XDG workspace registry (standalone, no red_pill import). None if absent."""
	path = os.path.join(home, ".config", "red-pill", "workspaces.yaml")
	if not os.path.exists(path):
		return None
	try:
		import yaml

		with open(path, encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
		ac = data.get("agent_core")
		return os.path.expanduser(ac) if ac else None
	except Exception:
		return None


def agent_core_vars():
	"""Resolve ${AGENT_CORE_DIR} (the agent's GLOBAL desk). Source of truth: the workspace registry
	(~/.config/red-pill/workspaces.yaml:agent_core); falls back to the flat .env for back-compat.
	WORKSPACE_ROOT/USER_ATLAS_DIR are no longer emitted — the atlas is per-project (registry / .agent)."""
	home = os.path.expanduser("~")
	agent_core = _agent_core_from_registry(home)
	if not agent_core:
		raw = parse_env_file(os.path.join(home, ".config", "red-pill", ".env"))
		ws = os.environ.get("WORKSPACE_ROOT") or raw.get("WORKSPACE_ROOT") or os.path.join(home, "Documents", "IA")
		ws = os.path.expanduser(ws.replace("${HOME}", home))
		val = os.environ.get("AGENT_CORE_DIR") or raw.get("AGENT_CORE_DIR") or os.path.join(ws, "Agent_Core")
		val = os.path.expanduser(val.replace("${WORKSPACE_ROOT}", ws).replace("${HOME}", home))
		agent_core = val
	return {"AGENT_CORE_DIR": agent_core}


def workspace_access_dirs():
	"""Standalone reader (no red_pill import): filesystem dirs to GRANT from the registry.
	Returns root (+ atlas if set) of every workspace with access: true. Empty on absence/error.
	The single operator switch (workspaces.yaml:access) → the per-IDE adapters translate it."""
	home = os.path.expanduser("~")
	path = os.path.join(home, ".config", "red-pill", "workspaces.yaml")
	if not os.path.exists(path):
		return []
	try:
		import yaml

		with open(path, encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
	except Exception:
		return []
	dirs = []
	for entry in data.get("workspaces") or []:
		if not isinstance(entry, dict) or not entry.get("access"):
			continue
		for key in ("root", "atlas"):
			val = entry.get(key)
			if val:
				resolved = os.path.expanduser(str(val))
				if resolved not in dirs:
					dirs.append(resolved)
	return dirs


def workspace_memory_dirs():
	"""Standalone reader (no red_pill import): returns memory dirs of all workspaces with memory enabled.
	If memory is True -> resolves to <root>/.red-pill/memory
	If memory is a string -> resolves relative to <root> if relative, else absolute.
	If memory is False/null/absent -> ignored."""
	home = os.path.expanduser("~")
	path = os.path.join(home, ".config", "red-pill", "workspaces.yaml")
	if not os.path.exists(path):
		return []
	try:
		import yaml

		with open(path, encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
	except Exception:
		return []
	dirs = []
	for entry in data.get("workspaces") or []:
		if not isinstance(entry, dict):
			continue
		mem = entry.get("memory")
		root = entry.get("root")
		if not mem or not root:
			continue
		root_resolved = os.path.expanduser(str(root))
		if isinstance(mem, bool) and mem:
			resolved = os.path.join(root_resolved, ".red-pill", "memory")
		elif isinstance(mem, str) and mem.strip():
			mem_str = mem.strip()
			if mem_str.lower() in ("true", "yes", "on"):
				resolved = os.path.join(root_resolved, ".red-pill", "memory")
			elif mem_str.lower() in ("false", "no", "off"):
				continue
			else:
				mem_path = os.path.expanduser(mem_str)
				if os.path.isabs(mem_path):
					resolved = mem_path
				else:
					resolved = os.path.abspath(os.path.join(root_resolved, mem_path))
		else:
			continue
		if resolved not in dirs:
			dirs.append(resolved)
	return dirs
