"""Índice de sesiones vivas — enriquecimiento + consumo (RFC-DESPERTAR-001, P1a).

Parte del latido (`session_liveness`) y lo enriquece para responder **quién /
dónde / qué** sin que el agente tenga que ir a mano a `opencode.db`.

- **presencia** (`board_line`, barato): nº de sesiones activas para el handshake-mini; SILENT salvo que haya **otra** viva.
- **detalle** (`build_board`): por sesión `provider`, `origin`, `directory`, `project`, `title`, `model`, `in_flight`, `last_activity`; consumido por MCP `session_board`.

Determinista; non-fatal. La inferencia de proyecto por **rutas tocadas** y el
tema rodante por Laya tags son P1b (ver §8 del RFC).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import red_pill.config as cfg
from red_pill.core import origins
from red_pill.core.paths import get_state_dir
from red_pill.core.session_liveness import SessionSignal, list_sessions

logger = logging.getLogger(__name__)

# Tope de parámetros por `IN (...)`: holgado bajo el límite histórico de SQLite (999).
_SQL_CHUNK = 500


def _active_seconds() -> int:
	return int(getattr(cfg.get_config(), "SESSION_ACTIVE_MIN", 10)) * 60


def _opencode_db_path() -> Path:
	xdg = os.environ.get("XDG_DATA_HOME")
	base = Path(xdg) if xdg else Path.home() / ".local" / "share"
	return base / "opencode" / "opencode.db"


def _opencode_meta(session_id: str) -> Dict[str, Any]:
	"""cwd/título/modelo de una sesión opencode (read-only, guarded)."""
	db = _opencode_db_path()
	if not db.exists():
		return {}
	try:
		con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
		con.row_factory = sqlite3.Row
		try:
			row = con.execute("SELECT directory, title, model FROM session WHERE id = ?", (session_id,)).fetchone()
		finally:
			con.close()
		if not row:
			return {}
		return {"directory": row["directory"], "title": row["title"], "model": row["model"]}
	except Exception as e:
		logger.debug(f"[SessionIndex] opencode meta failed for {session_id}: {e}")
		return {}


def _opencode_subsessions(session_ids: List[str]) -> Set[str]:
	"""Ids (de `session_ids`) que en `opencode.db` son **sub-sesiones** (`parent_id` no nulo).

	`chat.message` salta también en las sesiones hijas (tool `task`, paneles de
	subagentes), así que dejan latido propio; pero no son sesiones del operador:
	mientras corren, el turno del padre ya está en vuelo. Read-only y non-fatal:
	ante cualquier fallo devuelve vacío (mejor contar de más que esconder una sesión).
	"""
	ids = [sid for sid in dict.fromkeys(session_ids) if sid]
	db = _opencode_db_path()
	if not ids or not db.exists():
		return set()
	children: Set[str] = set()
	try:
		con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
		try:
			for i in range(0, len(ids), _SQL_CHUNK):
				chunk = ids[i : i + _SQL_CHUNK]
				marks = ",".join("?" * len(chunk))
				rows = con.execute(f"SELECT id FROM session WHERE parent_id IS NOT NULL AND id IN ({marks})", chunk).fetchall()
				children.update(r[0] for r in rows)
		finally:
			con.close()
	except Exception as e:
		logger.debug(f"[SessionIndex] opencode subsessions lookup failed: {e}")
		return set()
	return children


def _top_level(signals: List[SessionSignal]) -> List[SessionSignal]:
	"""Descarta los latidos de sub-sesiones opencode (el padre ya representa el trabajo)."""
	children = _opencode_subsessions([s.session_id for s in signals if s.provider == "opencode"])
	if not children:
		return list(signals)
	return [s for s in signals if not (s.provider == "opencode" and s.session_id in children)]


def _owning_workspace(directory: Optional[str]) -> Optional[str]:
	"""Nombre del workspace registrado que contiene `directory` (el más específico)."""
	if not directory:
		return None
	try:
		from red_pill.core.workspaces import list_workspaces

		target = Path(directory).resolve()
	except Exception:
		return None
	best: Optional[str] = None
	best_len = -1
	try:
		for ws in list_workspaces():
			try:
				root = ws.root.resolve()
			except Exception:
				continue
			if (target == root or root in target.parents) and len(str(root)) > best_len:
				best, best_len = ws.name, len(str(root))
	except Exception:
		return None
	return best


def _origin_for(provider: str, session_id: str) -> Optional[str]:
	try:
		meta = origins.read_origins(provider).get(session_id) or {}
		return meta.get("origin")
	except Exception:
		return None


def build_board(active_seconds: Optional[int] = None) -> List[Dict[str, Any]]:
	"""Lista enriquecida de sesiones (más reciente primero)."""
	if active_seconds is None:
		active_seconds = _active_seconds()
	board: List[Dict[str, Any]] = []
	for s in _top_level(list_sessions()):
		extra = _opencode_meta(s.session_id) if s.provider == "opencode" else {}
		board.append(
			{
				"provider": s.provider,
				"session_id": s.session_id,
				"origin": _origin_for(s.provider, s.session_id) or "user",
				"in_flight": s.in_flight,
				"active": s.is_active(active_seconds=active_seconds),
				"last_activity": s.last_mtime,
				"directory": extra.get("directory"),
				"project": _owning_workspace(extra.get("directory")),
				"title": extra.get("title"),
				"model": extra.get("model"),
			}
		)
	return board


def board_line() -> str:
	"""Línea de presencia para el handshake-mini (barata — solo el latido).

	SILENT salvo que haya **otra** sesión viva (>= 2 activas incluyendo la mía):
	"1" es lo normal y no aporta; el detalle va por MCP `session_board`. Las
	sub-sesiones opencode no cuentan; `opencode.db` solo se consulta cuando hay
	>= 2 candidatas (el caso normal no sale del directorio de latidos).
	"""
	try:
		active_seconds = _active_seconds()
		active = [s for s in list_sessions() if s.is_active(active_seconds=active_seconds)]
		if len(active) >= 2:
			active = _top_level(active)
	except Exception:
		return ""
	n = len(active)
	if n >= 2:
		return f"[BOARD: {n} sesiones vivas] (detalle: MCP `session_board`)"
	return ""


def session_index_path() -> Path:
	return get_state_dir() / "sessions_index.json"


def write_index(board: Optional[List[Dict[str, Any]]] = None) -> Path:
	"""Persiste el índice (best-effort) para otros consumidores (p.ej. pulse)."""
	board = board if board is not None else build_board()
	path = session_index_path()
	try:
		path.write_text(
			json.dumps({"updated_at": time.time(), "sessions": board}, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
	except Exception as e:
		logger.debug(f"[SessionIndex] write failed: {e}")
	return path


def read_index() -> List[Dict[str, Any]]:
	try:
		data = json.loads(session_index_path().read_text(encoding="utf-8"))
		return data.get("sessions", []) if isinstance(data, dict) else []
	except Exception:
		return []
