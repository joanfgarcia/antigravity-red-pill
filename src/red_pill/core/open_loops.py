"""OPEN LOOPS — digest determinista de lo que espera al agente al abrir sesión.

Sin LLM. Reúne la información que hoy **no** se inyecta y que un modelo menos
capaz necesita para no rellenar huecos a ciegas: decisiones pendientes del
Operador (notas del despertar), RFCs del desk bloqueados/pausados, y shards
`OPEN` del workspace. Formato compacto, una línea; silencioso si no hay nada.

Nunca lanza: cualquier fallo degrada a la parte que sí se pudo leer.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

_STATE_JSONS = ("opencode_session.json", "claude_code_session.json")
_CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, str]] = {}


def _desk_root(desk: Optional[Path | str]) -> Path:
	if desk is not None:
		return Path(desk)
	from red_pill.core.paths import get_agent_core_root

	return get_agent_core_root()


def _current_workspace() -> Path:
	"""Workspace del agente: env → bridge del arnés (más reciente) → cwd.

	El interceptor corre dentro del MCP (cwd = checkout del kernel), así que el
	cwd NO es el workspace del agente; se reusa el bridge que el hook escribe
	(`state/<harness>_session.json` → `workdir`).
	"""
	env = os.getenv("REDPILL_WORKSPACE")
	if env and os.path.isdir(env):
		return Path(env)
	try:
		from red_pill.core.paths import get_state_dir

		state = get_state_dir()
		best: Optional[tuple[float, Path]] = None
		for name in _STATE_JSONS:
			try:
				data = json.loads((state / name).read_text(encoding="utf-8"))
			except Exception:
				continue
			if not isinstance(data, dict):
				continue
			workdir = str(data.get("workdir") or "").strip()
			if not workdir or not os.path.isdir(workdir):
				continue
			updated = float(data.get("updated_at") or 0.0)
			if best is None or updated > best[0]:
				best = (updated, Path(workdir))
		if best is not None:
			return best[1]
	except Exception:
		pass
	return Path.cwd()


def _planner_loops(desk: Path) -> tuple[int, list[str]]:
	"""RFCs/ítems del planner en `blocked`/`paused` (con `reason` o sin él)."""
	root = desk / "planner"
	if not root.is_dir():
		return 0, []
	from red_pill.core.awakening_channel import parse_frontmatter

	names: list[str] = []
	for f in sorted(root.rglob("*.md")):
		if any(part.startswith(".") for part in f.parts):
			continue
		try:
			head = f.read_text(encoding="utf-8", errors="ignore")
		except Exception:
			continue
		fm, _ = parse_frontmatter(head)
		status = str(fm.get("status") or "").strip().casefold()
		if status in ("blocked", "paused"):
			names.append(str(fm.get("id") or f.parent.name or f.stem))
	return len(names), names


def _shards_open(workspace: Path) -> int:
	try:
		data = json.loads((workspace / ".cell" / "shards.json").read_text(encoding="utf-8"))
	except Exception:
		return 0
	shards = data.get("shards") if isinstance(data, dict) else data
	if not isinstance(shards, list):
		return 0
	return sum(1 for s in shards if isinstance(s, dict) and str(s.get("status", "")).upper() == "OPEN")


def open_loops_line(desk: Optional[Path | str] = None, workspace: Optional[Path | str] = None) -> str:
	"""Una línea `OPEN LOOPS: …` con lo pendiente, o `""` si no hay nada."""
	desk_p = _desk_root(desk)
	ws_p = Path(workspace) if workspace is not None else _current_workspace()
	key = f"{desk_p}|{ws_p}"
	now = time.time()
	cached = _cache.get(key)
	if cached and now - cached[0] < _CACHE_TTL_S:
		return cached[1]

	parts: list[str] = []
	try:
		from red_pill.core.awakening_channel import count_for_operator

		n = count_for_operator(desk_p)
		if n > 0:
			parts.append(f"{n} decisión(es) del Operador")
	except Exception:
		pass
	try:
		n, _names = _planner_loops(desk_p)
		if n > 0:
			parts.append(f"{n} RFC blocked/paused")
	except Exception:
		pass
	try:
		n = _shards_open(ws_p)
		if n > 0:
			parts.append(f"{n} shards OPEN")
	except Exception:
		pass

	line = "OPEN LOOPS: " + " · ".join(parts) if parts else ""
	_cache[key] = (now, line)
	return line
