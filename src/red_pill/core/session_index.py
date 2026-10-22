"""Índice de sesiones vivas — enriquecimiento + consumo (RFC-DESPERTAR-001, P1a).

Parte del latido (`session_liveness`) y lo enriquece para responder **quién /
dónde / qué** sin que el agente tenga que ir a mano a `opencode.db`.

- **presencia** (`board_line`, barato): nº de sesiones activas para el handshake-mini; SILENT salvo que haya **otra** viva.
- **detalle** (`build_board`): por sesión `provider`, `origin`, `directory`, `project`/`projects` (inferidos por **rutas tocadas**, ponderados por frecuencia → `workspace_owners`, fallback cwd), `topic` (tema rodante Laya), `title`, `model`, `in_flight`, `last_activity`, `touched_files`; consumido por MCP `session_board`.

Determinista; non-fatal (RFC-DESPERTAR-001 P1b core).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import red_pill.config as cfg
from red_pill.core import origins
from red_pill.core.paths import get_state_dir
from red_pill.core.session_liveness import SessionSignal, list_sessions
from red_pill.core.workspaces import workspace_owners

logger = logging.getLogger(__name__)

# Tope de parámetros por `IN (...)`: holgado bajo el límite histórico de SQLite (999).
_SQL_CHUNK = 500


def _active_seconds() -> int:
	return int(getattr(cfg.get_config(), "SESSION_ACTIVE_MIN", 10)) * 60


def _opencode_db_path() -> Path:
	from red_pill.core.paths import get_xdg_data_home

	return get_xdg_data_home() / "opencode" / "opencode.db"


def _format_model(raw: Any) -> Optional[str]:
	"""`session.model` de opencode (JSON `{"id", "providerID", "variant"}`) → `provider/model`.

	Texto que no es JSON se devuelve tal cual; vacío o sin `id` → None.
	"""
	if not raw:
		return None
	data = raw
	if isinstance(raw, str):
		try:
			data = json.loads(raw)
		except ValueError:
			return raw
	if isinstance(data, dict):
		model_id = data.get("id") or data.get("modelID")
		if not model_id:
			return None
		provider = data.get("providerID")
		return f"{provider}/{model_id}" if provider else str(model_id)
	return str(data)


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
		return {"directory": row["directory"], "title": row["title"], "model": _format_model(row["model"])}
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


# Keys de los inputs de tool calls que apuntan a un fichero o carpeta (ver los
# samples de opencode.db: read/write/edit → filePath, glob/grep → path, bash → workdir).
_PATH_KEYS = ("filePath", "file_path", "path", "workdir")

# Rutas absolutas (o `~/`) EMBEBIDAS en un token bash. Solo cuentan si empiezan
# el token o siguen a un separador: blanco (token entrecomillado con espacios),
# comillas, `=`/`:` (`--file=/x`, `PATH=/a:/b`) u operador shell (`&;|<>(`,
# `cd /x&&ls`). Así un relativo como `awakening/2026….log` no aporta un `/2026….log`
# falso. `//` (URLs) se descarta. El ruido que quede (/usr/bin, heredocs) no
# mapea a ningún workspace y la atribución lo ignora.
_ABS_PATH_RE = re.compile(r"(?<![^\s=:&;|<>(`'\"])~?/(?!/)[A-Za-z0-9._~@/-]+")
# Operadores shell pegados a una ruta sin espacios (`cd /x&&ls`, `/x;rm`).
_SHELL_META_RE = re.compile(r"[&;|<>()`$]")

# El proyecto se infiere de las últimas N rutas tocadas ("en los últimos turnos"),
# contando repeticiones: es una ventana de actividad, no de rutas distintas.
_RECENT_PATHS = 200


def _command_paths(cmd: str) -> List[str]:
	"""Rutas ABSOLUTAS (o `~/`) de un comando bash: tokens shell completos
	(respeta comillas y espacios) que empiezan por `/` o `~/`, y rutas embebidas
	en el resto tras un separador (`--file=/x`, `cd /x&&ls`; ver `_ABS_PATH_RE`).

	Los tokens RELATIVOS de un comando no se extraen ni se resuelven: no se sabe
	contra qué cwd corrió cada uno (un `cd` previo lo cambia). Solo las keys
	estructuradas relativas (`filePath`/`path`/`workdir`) se resuelven, contra el
	directorio de la sesión (`_touched_sequence`)."""
	try:
		tokens = shlex.split(cmd)
	except ValueError:
		tokens = cmd.split()
	out: List[str] = []
	for tok in tokens:
		if tok.startswith(("/", "~/")) and not _SHELL_META_RE.search(tok):
			out.append(tok)
		else:
			out.extend(_ABS_PATH_RE.findall(tok))
	return out


def _touched_sequence(
	session_id: str,
	base_dir: Optional[str] = None,
	*,
	newest_first: bool = False,
	limit: Optional[int] = None,
) -> List[str]:
	"""Rutas tocadas por la sesión, CON repeticiones y en orden cronológico.

	Extraídas de los tool parts de opencode.db: las keys estructuradas de los
	inputs (`filePath`/`path`/`workdir`) y, para `bash`, las rutas absolutas del
	comando (`_command_paths`). Las keys relativas se resuelven contra `base_dir`
	(el directorio de la sesión), nunca contra el cwd de este proceso; sin él se
	descartan. Determinista y non-fatal: cualquier fallo devuelve [] y el
	proyecto cae al fallback del cwd (RFC-DESPERTAR-001 §8.2).

	`newest_first`/`limit` sirven a la inferencia de rama (F3): solo las últimas
	rutas hacen falta y llegan de la más reciente a la más antigua.
	"""
	db = _opencode_db_path()
	if not db.exists():
		return []
	try:
		con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
		try:
			order = "DESC" if newest_first else "ASC"
			sql = f"SELECT data FROM part WHERE session_id = ? AND data LIKE '%\"tool\"%' ORDER BY time_created {order}"
			params: tuple = (session_id,)
			if limit:
				sql += " LIMIT ?"
				params = (session_id, int(limit))
			rows = con.execute(sql, params).fetchall()
		finally:
			con.close()
	except Exception as e:
		logger.debug(f"[SessionIndex] touched_paths failed for {session_id}: {e}")
		return []

	seq: List[str] = []

	def _add(p: str) -> None:
		if not p:
			return
		if not p.startswith(("/", "~")):
			if not base_dir:
				return
			p = os.path.normpath(os.path.join(base_dir, p))
		seq.append(p)

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
			for m in _command_paths(cmd):
				_add(m)
	return seq


def _rank_projects(paths: List[str]) -> List[str]:
	"""Workspaces dueños de `paths` (cronológicas), del más al menos relevante.

	Relevancia = nº de apariciones en la ventana; empate → el tocado más
	recientemente. Así un `ls` suelto en otro proyecto no le roba la sesión al
	proyecto en el que se está trabajando. Las rutas sin dueño no puntúan.
	"""
	score: Dict[str, List[int]] = {}
	for i, name in enumerate(workspace_owners(paths)):
		if name is None:
			continue
		hits = score.setdefault(name, [0, -1])
		hits[0] += 1
		hits[1] = i
	return sorted(score, key=lambda n: (-score[n][0], -score[n][1]))


# Inferencia de rama por repo TOCADO (F3 / D22): cacheada por sesión (TTL 60s),
# porque el handshake la consulta cada turno cuando el workspace del agente no es
# un repo. session_id -> (at, snapshot | None)
_INFER_TTL_S = 60.0
_INFER_CACHE: Dict[str, tuple] = {}


def infer_session_git(provider: str, session_id: str, *, use_cache: bool = True) -> Optional[Dict[str, Optional[str]]]:
	"""Snapshot git del repo que la sesión está TOCANDO (F3 / D22).

	Cuando el cwd del agente no es un repo (IDE abierto en una carpeta padre,
	p.ej. `~/Documents/IA`), la misión se resuelve por el repo de las **rutas
	tocadas** (P1b), no por el cwd. Solo opencode expone rutas tocadas
	(`opencode.db`); otros proveedores devuelven None (fallback a `adhoc`).

	Non-fatal y cacheado (TTL 60s): `{branch, worktree, head_commit}` del primer
	repo encontrado entre las últimas rutas, o None.
	"""
	from red_pill.core.gitinfo import git_snapshot

	if not session_id or provider != "opencode":
		return None
	now = time.time()
	if use_cache:
		hit = _INFER_CACHE.get(session_id)
		if hit and now - float(hit[0]) < _INFER_TTL_S:
			return dict(hit[1]) if hit[1] else None
	base = _opencode_meta(session_id).get("directory")
	snap: Optional[Dict[str, Optional[str]]] = None
	for path in _touched_sequence(session_id, base_dir=base, newest_first=True, limit=40):
		directory = path if os.path.isdir(path) else os.path.dirname(path)
		candidate = git_snapshot(directory)
		if candidate.get("worktree"):
			snap = candidate
			break
	if use_cache:
		_INFER_CACHE[session_id] = (now, snap)
	return dict(snap) if snap else None


# Tope de puntos leídos por sesión al buscar el último tema (paginando).
_THEME_SCAN_MAX = 2000

# Cliente Qdrant del módulo, creado al primer uso y reutilizado: el MCP server
# es de larga vida y el tablón se pide muchas veces. Un fallo al crearlo no se
# cachea (se reintenta en la siguiente petición).
_QDRANT_CLIENT: Any = None
_QDRANT_CLIENT_LOCK = threading.Lock()


def _qdrant_client() -> Any:
	"""Cliente Qdrant compartido (lazy). Solo el cliente (`StorageEngine`, con su
	kill-switch SEC-CR-02): nada de `MemoryManager`, que carga embeddings/torch
	para una consulta que no los necesita. Propaga el error si no se puede crear."""
	global _QDRANT_CLIENT
	with _QDRANT_CLIENT_LOCK:
		if _QDRANT_CLIENT is None:
			from red_pill.core.storage import StorageEngine

			_QDRANT_CLIENT = StorageEngine(url=cfg.QDRANT_URL).client
		return _QDRANT_CLIENT


def _query_latest_theme(session_id: str, client: Any = None) -> Optional[str]:
	"""Último `tag_theme` Laya de la sesión (interaction_memories), por timestamp.

	El tema rodante es "último turno gana": se toma el engrama etiquetado más
	reciente (`tagged_at`/`timestamp`). El scroll de Qdrant no ordena por payload
	(ids uuid4), así que se pagina la sesión entera (hasta `_THEME_SCAN_MAX`) en
	vez de mirar 50 puntos arbitrarios. None si no hay tags para la sesión.
	"""
	try:
		if client is None:
			client = _qdrant_client()
		from qdrant_client.http import models as _qm

		flt = _qm.Filter(
			must=[
				_qm.FieldCondition(key="metadata.session_id", match=_qm.MatchValue(value=session_id)),
				_qm.FieldCondition(key="tag_status", match=_qm.MatchValue(value="ok")),
			]
		)
		pts: List[Any] = []
		offset = None
		while len(pts) < _THEME_SCAN_MAX:
			page, offset = client.scroll(
				"interaction_memories",
				scroll_filter=flt,
				limit=256,
				offset=offset,
				with_payload=True,
				with_vectors=False,
			)
			pts.extend(page)
			if offset is None:
				break
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


def _theme_client() -> Any:
	"""El cliente Qdrant del módulo para el tema rodante (None si el etiquetado
	está apagado o no se puede crear el cliente)."""
	try:
		from red_pill.core.realtime_tag import enabled as _rt_enabled

		if not _rt_enabled():
			return None
		return _qdrant_client()
	except Exception as e:
		logger.debug(f"[SessionIndex] theme client unavailable: {e}")
		return None


def _registry_ttl_s() -> float:
	"""Ventana en que una fila del registro sin latido sigue mostrándose (reciente).

	`SESSION_BOARD_REGISTRY_TTL_H` (horas, default 12) — más generosa que el TTL de
	liveness: el registro es el "quién/qué misión", el latido solo el "vivo".
	"""
	try:
		return float(os.getenv("SESSION_BOARD_REGISTRY_TTL_H", "12")) * 3600.0
	except Exception:
		return 12 * 3600.0


def _load_registry() -> Dict[str, Dict[str, Any]]:
	"""Filas de `session_registry` por `originator` (best-effort; {} si falla).

	El tablón es una VISTA del registro (F2): sin `session.db` disponible degrada
	a lo que dan los latidos, nunca revienta.
	"""
	try:
		from red_pill.session.store import SessionRegistry

		return {r["originator"]: r for r in SessionRegistry().list_sessions()}
	except Exception as e:
		logger.debug(f"[SessionIndex] registry unavailable: {e}")
		return {}


# Campos del registro que el tablón expone (alma / misión / afinidad / espejo git).
_REGISTRY_FIELDS = (
	"continuity_id",
	"mission_id",
	"campaign_id",
	"role",
	"lineage_id",
	"affinity_json",
	"last_seen_global_turn",
	"branch",
	"worktree",
	"head_commit",
	"title",
	"intent",
)


def _attach_registry(entry: Dict[str, Any], row: Dict[str, Any]) -> None:
	"""Copia los campos de registro (no nulos) sobre una entrada del tablón."""
	for key in _REGISTRY_FIELDS:
		if row.get(key) is not None:
			entry[key] = row[key]
	if not entry.get("title"):
		entry["title"] = row.get("title")


def _registry_entry(row: Dict[str, Any], now: float) -> Dict[str, Any]:
	"""Entrada del tablón para una fila del registro SIN latido vivo (reciente)."""
	entry: Dict[str, Any] = {
		"provider": row.get("provider"),
		"session_id": row.get("session_id"),
		"origin": "user",
		"in_flight": False,
		"active": False,
		"last_activity": row.get("updated_at"),
		"directory": None,
		"project": None,
		"projects": [],
		"topic": None,
		"model": None,
		"touched_files": 0,
		"from_registry": True,
	}
	_attach_registry(entry, row)
	return entry


def build_board(active_seconds: Optional[int] = None) -> List[Dict[str, Any]]:
	"""Lista enriquecida de sesiones (más reciente primero).

	Fuente **primaria**: el registro (`session_registry` — alma/misión/afinidad/
	espejo git). Fuente de **liveness**: los latidos (`session_liveness`) y, para
	opencode, su `opencode.db`. El registro se une por `originator`
	(`provider:session_id`) y añade las filas sin latido reciente como
	"recientes" (F2: el tablón lee del registro, los latidos son el fallback).

	`projects` ordena los workspaces de las últimas `_RECENT_PATHS` rutas
	tocadas por frecuencia (empate → el más reciente, `_rank_projects`);
	`project` es el primero. Sin rutas atribuibles, el dueño del cwd.
	"""
	if active_seconds is None:
		active_seconds = _active_seconds()
	now = time.time()
	board: List[Dict[str, Any]] = []
	client = None
	client_ready = False
	for s in _top_level(list_sessions()):
		is_opencode = s.provider == "opencode"
		extra = _opencode_meta(s.session_id) if is_opencode else {}
		directory = extra.get("directory")
		touched = _touched_sequence(s.session_id, base_dir=directory) if is_opencode else []
		projects = _rank_projects(touched[-_RECENT_PATHS:])
		if not projects and directory:
			owner = _owning_workspace(directory)
			if owner:
				projects = [owner]
		if not client_ready:
			client, client_ready = _theme_client(), True
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
				"topic": _rolling_topic(s.session_id, client=client) if client is not None else None,
				"title": extra.get("title"),
				"model": extra.get("model"),
				"touched_files": len(set(touched)),
			}
		)
	# F2: el registro es la fuente primaria de identidad/misión; se une por
	# `originator` y lo que no tiene latido reciente entra como "reciente".
	registry = _load_registry()
	if registry:
		for b in board:
			row = registry.pop(f"{b.get('provider')}:{b.get('session_id')}", None)
			if row:
				_attach_registry(b, row)
		ttl = _registry_ttl_s()
		for row in registry.values():
			updated = row.get("updated_at")
			if isinstance(updated, (int, float)) and 0 < now - float(updated) <= ttl:
				board.append(_registry_entry(row, now))
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
	"""Persiste el índice (best-effort) para otros consumidores (p.ej. pulse).

	Atómico (tmp + `os.replace`): un lector concurrente ve el índice anterior o
	el nuevo, nunca uno a medio escribir.
	"""
	board = board if board is not None else build_board()
	path = session_index_path()
	tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
	try:
		tmp.write_text(
			json.dumps({"updated_at": time.time(), "sessions": board}, ensure_ascii=False, indent=2),
			encoding="utf-8",
		)
		os.replace(tmp, path)
	except Exception as e:
		logger.debug(f"[SessionIndex] write failed: {e}")
		try:
			tmp.unlink(missing_ok=True)
		except OSError:
			pass
	return path


def read_index() -> List[Dict[str, Any]]:
	try:
		data = json.loads(session_index_path().read_text(encoding="utf-8"))
		return data.get("sessions", []) if isinstance(data, dict) else []
	except Exception:
		return []


def _age(ts: Optional[float], now: float) -> str:
	if ts is None:
		return ""
	mins = max(0, int((now - ts) // 60))
	if mins < 60:
		return f" · hace {mins} min"
	return f" · hace {mins // 60} h"


def _render_entry(b: Dict[str, Any], active_min: int, now: float) -> List[str]:
	if b.get("active"):
		state = "en vuelo"
	elif b.get("in_flight"):
		state = f"en vuelo > {active_min} min (¿huérfana?)"
	else:
		state = "idle"
	lines = [f"[{b['provider']}] {b['session_id']} · {b.get('origin')} · {state}{_age(b.get('last_activity'), now)}"]
	detail = []
	if b.get("project"):
		others = [x for x in b.get("projects") or [] if x != b["project"]]
		detail.append(f"proyecto={b['project']}" + (f" (+{', '.join(others)})" if others else ""))
	if b.get("topic"):
		detail.append(f"tema={b['topic']}")
	if b.get("mission_id"):
		detail.append(f"misión={b['mission_id']}")
	if b.get("continuity_id"):
		detail.append(f"alma={str(b['continuity_id'])[:8]}")
	if b.get("branch"):
		detail.append(f"rama={b['branch']}")
	if b.get("directory"):
		detail.append(f"cwd={b['directory']}")
	if b.get("title"):
		detail.append(f"título={b['title']}")
	if b.get("model"):
		detail.append(f"modelo={b['model']}")
	if detail:
		lines.append("\t- " + " | ".join(detail))
	return lines


def render_board(board: List[Dict[str, Any]], active_min: Optional[int] = None, now: Optional[float] = None) -> str:
	"""Texto del MCP `session_board`.

	Separa las **vivas** (turno en vuelo con inicio reciente: `active`) de las
	**recientes** (latidos que el Janitor aún retiene, TTL `SESSION_LIVENESS_TTL_H`):
	tener latido no es estar vivo.
	"""
	if active_min is None:
		active_min = _active_seconds() // 60
	now = time.time() if now is None else now
	if not board:
		return "[SESSION BOARD] Sin sesiones vivas ni recientes."
	live = [b for b in board if b.get("active")]
	recent = [b for b in board if not b.get("active")]
	lines = [f"--- SESSION BOARD: {len(live)} viva(s) · {len(recent)} reciente(s) ---"]
	misiones: Dict[str, int] = {}
	for b in board:
		m = b.get("mission_id")
		if m:
			misiones[m] = misiones.get(m, 0) + 1
	if misiones:
		ranked = sorted(misiones.items(), key=lambda kv: (-kv[1], kv[0]))
		lines.append("Misiones: " + " · ".join(f"{m} ({n})" for m, n in ranked))
	if live:
		lines.append(f"Vivas (turno en vuelo, iniciado hace < {active_min} min):")
		for b in live:
			lines.extend(_render_entry(b, active_min, now))
	if recent:
		lines.append("Recientes (sin turno en vuelo; latidos aún no purgados):")
		for b in recent:
			lines.extend(_render_entry(b, active_min, now))
	return "\n".join(lines)
