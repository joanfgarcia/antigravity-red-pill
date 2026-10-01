"""Índice de sesiones vivas — enriquecimiento + consumo (RFC-DESPERTAR-001, P1a).

Parte del latido (`session_liveness`) y lo enriquece para responder **quién /
dónde / qué** sin que el agente tenga que ir a mano a `opencode.db`.

- **presencia** (`board_line`, barato): nº de sesiones activas para el handshake-mini; SILENT salvo que haya **otra** viva.
- **detalle** (`build_board`): por sesión `provider`, `origin`, `directory`, `project`/`projects` (inferidos por **rutas tocadas** → `infer_workspaces`, fallback cwd), `topic` (tema rodante Laya), `title`, `model`, `in_flight`, `last_activity`, `touched_files`; consumido por MCP `session_board`.

Determinista; non-fatal (RFC-DESPERTAR-001 P1b core).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import red_pill.config as cfg
from red_pill.core import origins
from red_pill.core.paths import get_state_dir
from red_pill.core.session_liveness import list_sessions
from red_pill.core.workspaces import infer_workspaces

logger = logging.getLogger(__name__)


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


# Keys de los inputs de tool calls que apuntan a un fichero o carpeta (ver los
# samples de opencode.db: read/write/edit → filePath, glob/grep → path, bash → workdir).
_PATH_KEYS = ("filePath", "file_path", "path", "workdir")

# Rutas absolutas embebidas en comandos bash. Heurística deliberadamente ancha:
# el ruido (URLs, /usr/bin, heredocs) no mapea a ningún workspace y `infer_workspaces`
# lo descarta. Lo que importa es no perder la ruta real tocada.
_ABS_PATH_RE = re.compile(r"/[A-Za-z0-9._~@/-]+")


def _touched_paths(session_id: str) -> List[str]:
	"""Rutas tocadas por la sesión, extraídas de los tool parts de opencode.db.

	Lee las keys estructuradas de los inputs (`filePath`/`path`/`workdir`) y, para
	`bash`, las rutas absolutas del comando. Orden de primera aparición, sin
	duplicados. Determinista y non-fatal: cualquier fallo devuelve [] y el proyecto
	cae al fallback del cwd (RFC-DESPERTAR-001 §8.2).
	"""
	db = _opencode_db_path()
	if not db.exists():
		return []
	try:
		con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
		try:
			rows = con.execute(
				"SELECT data FROM part WHERE session_id = ? AND data LIKE '%\"tool\"%' ORDER BY time_created ASC",
				(session_id,),
			).fetchall()
		finally:
			con.close()
	except Exception as e:
		logger.debug(f"[SessionIndex] touched_paths failed for {session_id}: {e}")
		return []

	out: List[str] = []
	seen: set = set()

	def _add(p: str) -> None:
		if p and p not in seen:
			seen.add(p)
			out.append(p)

	for (raw,) in rows:
		try:
			d = json.loads(raw)
		except Exception:
			continue
		if d.get("type") != "tool":
			continue
		inp = (d.get("state") or {}).get("input")
		if not isinstance(inp, dict):
			continue
		for key in _PATH_KEYS:
			v = inp.get(key)
			if isinstance(v, str):
				_add(v)
		cmd = inp.get("command")
		if isinstance(cmd, str):
			for m in _ABS_PATH_RE.findall(cmd):
				_add(m)
	return out


def _query_latest_theme(session_id: str, client: Any = None) -> Optional[str]:
	"""Último `tag_theme` Laya de la sesión (interaction_memories), por timestamp.

	El tema rodante es "último turno gana": se toma el engrama etiquetado más
	reciente (`tagged_at`/`timestamp`). None si no hay tags para la sesión.
	"""
	try:
		if client is None:
			from red_pill.memory import MemoryManager

			client = MemoryManager().client
		from qdrant_client.http import models as _qm

		pts, _ = client.scroll(
			"interaction_memories",
			scroll_filter=_qm.Filter(
				must=[
					_qm.FieldCondition(key="metadata.session_id", match=_qm.MatchValue(value=session_id)),
					_qm.FieldCondition(key="tag_status", match=_qm.MatchValue(value="ok")),
				]
			),
			limit=50,
			with_payload=True,
			with_vectors=False,
		)
	except Exception as e:
		logger.debug(f"[SessionIndex] theme query failed for {session_id}: {e}")
		return None

	best: Optional[str] = None
	best_ts = -1.0
	for p in pts:
		pl = p.payload or {}
		theme = pl.get("tag_theme")
		if not theme:
			continue
		try:
			ts = float(pl.get("tagged_at") or pl.get("timestamp") or 0.0)
		except (TypeError, ValueError):
			ts = 0.0
		if ts >= best_ts:
			best, best_ts = str(theme), ts
	return best


def _rolling_topic(session_id: str, *, client: Any = None) -> Optional[str]:
	"""Tema rodante por Laya tags (RFC-004 → RFC-DESPERTAR-001 §8.3).

	None si el etiquetado está desactivado o no hay tema para la sesión. Non-fatal:
	el tablón no depende del sidecar ni de Qdrant para seguir funcionando.
	"""
	try:
		from red_pill.core.realtime_tag import enabled as _rt_enabled

		if not _rt_enabled():
			return None
	except Exception:
		return None
	return _query_latest_theme(session_id, client=client)


def _owning_workspace(directory: Optional[str]) -> Optional[str]:
	"""Nombre del workspace registrado que contiene `directory` (el más específico)."""
	if not directory:
		return None
	from red_pill.core.workspaces import owning_workspace

	return owning_workspace(directory)


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
	for s in list_sessions():
		is_opencode = s.provider == "opencode"
		extra = _opencode_meta(s.session_id) if is_opencode else {}
		touched = _touched_paths(s.session_id) if is_opencode else []
		projects = infer_workspaces(touched)
		directory = extra.get("directory")
		if not projects and directory:
			owner = _owning_workspace(directory)
			if owner:
				projects = [owner]
		board.append(
			{
				"provider": s.provider,
				"session_id": s.session_id,
				"origin": _origin_for(s.provider, s.session_id) or "user",
				"in_flight": s.in_flight,
				"active": s.is_active(active_seconds=active_seconds),
				"last_activity": s.last_mtime,
				"directory": directory,
				"project": projects[0] if projects else None,
				"projects": projects,
				"topic": _rolling_topic(s.session_id),
				"title": extra.get("title"),
				"model": extra.get("model"),
				"touched_files": len(touched),
			}
		)
	return board


def board_line() -> str:
	"""Línea de presencia para el handshake-mini (barata — solo el latido).

	SILENT salvo que haya **otra** sesión viva (>= 2 activas incluyendo la mía):
	"1" es lo normal y no aporta; el detalle va por MCP `session_board`.
	"""
	try:
		n = sum(1 for s in list_sessions() if s.is_active(active_seconds=_active_seconds()))
	except Exception:
		return ""
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
