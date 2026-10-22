"""Snapshot git de un directorio de trabajo (Alma y Coro, Fase 0b).

Best-effort y cacheado: `branch` / `worktree` / `head_commit` del **workspace del
agente** — resueltos con `git -C <dir>`, nunca con el cwd del proceso MCP (que es
el checkout del kernel, no donde trabaja el agente). La caché (TTL 60s) evita un
subprocess por turno en el hot path del handshake (`<20 ms`).

Puro respeto a la regla de capas: no importa nada de `red_pill` y no lanza —
cualquier fallo degrada a "sin repo" (todos los campos `None`).
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_TTL_S = 60.0
_EMPTY: Dict[str, Optional[str]] = {"branch": None, "worktree": None, "head_commit": None}
# dir abspath -> (at, snapshot)
_CACHE: Dict[str, tuple] = {}


def _git(args: list, cwd: str, timeout: float = 2.0) -> Optional[str]:
	"""`git -C cwd <args>` → stdout limpio o None (fallo/timeout/`HEAD` literal)."""
	try:
		out = subprocess.run(
			["git", "-C", cwd, *args],
			capture_output=True,
			text=True,
			timeout=timeout,
		)
	except Exception:
		return None
	if out.returncode != 0:
		return None
	value = out.stdout.strip()
	return value or None


def git_snapshot(workdir: Optional[str] = None, *, use_cache: bool = True) -> Dict[str, Optional[str]]:
	"""`{branch, worktree, head_commit}` del repo que contiene `workdir`.

	`worktree` es la raíz del árbol de trabajo (`--show-toplevel`; en un `git worktree`
	enlazado es el directorio del worktree, no el repo principal). `branch` es la rama
	actual (`None` si detached). `head_commit` es el sha de HEAD. Todos `None` si
	`workdir` no es un directorio o no vive en un repo git.
	"""
	if not workdir:
		return dict(_EMPTY)
	path = os.path.abspath(workdir)
	if not os.path.isdir(path):
		return dict(_EMPTY)
	now = time.time()
	if use_cache:
		hit = _CACHE.get(path)
		if hit and now - float(hit[0]) < _TTL_S:
			return dict(hit[1])
	worktree = _git(["rev-parse", "--show-toplevel"], path)
	if not worktree:
		if use_cache:
			_CACHE[path] = (now, _EMPTY)
		return dict(_EMPTY)
	branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], path)
	if branch == "HEAD":  # detached HEAD: no hay rama
		branch = None
	snap = {"branch": branch, "worktree": worktree, "head_commit": _git(["rev-parse", "HEAD"], path)}
	if use_cache:
		_CACHE[path] = (now, snap)
	return dict(snap)


def clear_cache() -> None:
	"""Vacía la caché (tests y, si hiciera falta, invalidación manual)."""
	_CACHE.clear()
