"""`session.db` — reloj global, registro de sesiones y espejo canónico (Alma y Coro).

El registro (`session_registry`) es el tablón: una fila por `originator`
(leg, `provider:session_id`), con su alma (`continuity_id`), misión, rol y linaje.
El reloj (`global_turn_seq`) da monotonicidad a los turnos (que `memory_queue.id`
no puede, por el dedup que devuelve ids existentes). El espejo canónico
(`session_mirror`, Fase 1a) guarda los turnos portables que permiten reencarnar
el alma en otro cuerpo (`mirror.SessionMirror`).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

from red_pill.core.affinity import canonize_affinity
from red_pill.core.paths import get_session_db

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS global_turn_seq (
global_turn INTEGER PRIMARY KEY AUTOINCREMENT,
created_at REAL NOT NULL,
originator TEXT NOT NULL,
affinity_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_registry (
originator TEXT PRIMARY KEY,
continuity_id TEXT NOT NULL,
mission_id TEXT NOT NULL,
campaign_id TEXT,
role TEXT NOT NULL DEFAULT 'task',
lineage_id TEXT,
provider TEXT NOT NULL,
session_id TEXT NOT NULL,
last_seen_global_turn INTEGER NOT NULL DEFAULT 0,
last_seen_event_seq INTEGER NOT NULL DEFAULT 0,
affinity_json TEXT NOT NULL DEFAULT '[]',
updated_at REAL NOT NULL,
title TEXT,
branch TEXT,
worktree TEXT,
base_commit TEXT,
head_commit TEXT,
dirty_hash TEXT,
intent TEXT,
ttl_state TEXT NOT NULL DEFAULT 'active',
ttl_checked_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_registry_provider ON session_registry(provider);
CREATE INDEX IF NOT EXISTS idx_registry_ttl ON session_registry(ttl_state, updated_at);
CREATE INDEX IF NOT EXISTS idx_registry_soul ON session_registry(continuity_id);
CREATE INDEX IF NOT EXISTS idx_registry_mission ON session_registry(mission_id, ttl_state);

CREATE TABLE IF NOT EXISTS mission_events (
event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
event_id TEXT NOT NULL UNIQUE,
type TEXT NOT NULL,
mission_id TEXT NOT NULL,
campaign_id TEXT,
continuity_id TEXT,
originator TEXT,
global_turn INTEGER NOT NULL DEFAULT 0,
summary TEXT NOT NULL,
ref TEXT,
sealed INTEGER NOT NULL DEFAULT 0,
created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_mission ON mission_events(mission_id, event_seq);
CREATE INDEX IF NOT EXISTS idx_events_type ON mission_events(type, created_at);

CREATE TRIGGER IF NOT EXISTS mission_events_no_update BEFORE UPDATE ON mission_events
BEGIN
	SELECT RAISE(ABORT, 'mission_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS mission_events_no_delete BEFORE DELETE ON mission_events
BEGIN
	SELECT RAISE(ABORT, 'mission_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS mission_events_no_replace BEFORE INSERT ON mission_events
WHEN EXISTS (SELECT 1 FROM mission_events WHERE event_id = NEW.event_id)
	OR (NEW.event_seq IS NOT NULL AND EXISTS (SELECT 1 FROM mission_events WHERE event_seq = NEW.event_seq))
BEGIN
	SELECT RAISE(ABORT, 'mission_events is append-only (event_id/event_seq duplicado)');
END;

CREATE TABLE IF NOT EXISTS session_mirror (
id INTEGER PRIMARY KEY AUTOINCREMENT,
continuity_id TEXT NOT NULL,
mission_id TEXT NOT NULL,
global_turn INTEGER NOT NULL DEFAULT 0,
seq INTEGER NOT NULL,
role TEXT NOT NULL,
content TEXT,
tool_calls TEXT,
tool_call_id TEXT,
model TEXT,
ts REAL NOT NULL DEFAULT 0,
originator TEXT NOT NULL DEFAULT '',
source TEXT NOT NULL DEFAULT '',
source_ref TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mirror_seq ON session_mirror(continuity_id, seq);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mirror_source ON session_mirror(continuity_id, originator, source_ref)
WHERE source_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mirror_ts ON session_mirror(continuity_id, ts);
"""

# Taxonomía civil de eventos de misión (Fase 2, RFC_CONSCIENCIA_MULTISESION §3.6).
# Cerrada: un tipo desconocido se rechaza (fail-closed).
EVENT_TYPES = frozenset(
	{
		"phase_done",
		"commit",
		"claim_acquired",
		"claim_released",
		"blocked",
		"unblocked",
		"awaiting_operator",
		"intent_updated",
		"mission_closed",
		"objection",
	}
)

_EVENT_SUMMARY_MAX = 800
_EVENT_REF_MAX = 400
_EVENT_ID_MAX = 200
_EVENT_RATE_PER_MIN = 30

# Anti-inyección del canal del coro: controles/ANSI, bidi y zero-width fuera;
# una sola línea; y `<`/`>` neutralizados (un `<session/>` forjado no se parsea).
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\ufeff]+")
_SPACE_RE = re.compile(r"\s+")


def _clean_text(value: object, cap: int) -> str:
	"""Texto de evento seguro: una línea, sin controles/ANSI ni `<>`, recortado."""
	text = _CONTROL_RE.sub(" ", str(value if value is not None else ""))
	text = _SPACE_RE.sub(" ", text).strip()
	text = text.replace("<", "‹").replace(">", "›")
	return text[:cap].strip()


def sanitize_inline(value: object, cap: int = 200) -> str:
	"""Saneado público para interpolar un valor en una línea de render."""
	return _clean_text(value, cap)


def _clean_key(value: object, cap: int = _EVENT_ID_MAX) -> str:
	"""Clave de identidad (misión/originator/campaña): controles fuera y cap.

	NO neutraliza `<>`: son válidos en ramas git y neutralizarlos en la clave
	rompería la búsqueda (se guardaría distinto de como se consulta). El render
	es quien los neutraliza (`sanitize_inline`).
	"""
	text = _CONTROL_RE.sub(" ", str(value if value is not None else ""))
	return _SPACE_RE.sub(" ", text).strip()[:cap].strip()


def _split_originator(originator: str) -> tuple[str, str]:
	"""`provider:session_id` → (provider, session_id). Sin `:` = (originator, '')."""
	provider, _, session_id = originator.partition(":")
	return (provider or originator), session_id


@contextmanager
def connect_session_db(db_path: str) -> Iterator[sqlite3.Connection]:
	"""Conexión a `session.db` (WAL + busy_timeout), compartida por store y espejo."""
	conn = sqlite3.connect(db_path, timeout=30.0)
	try:
		# busy_timeout ANTES del WAL: el pragma de journal no usa el handler y
		# en un arranque concurrente en frío puede dar "database is locked".
		conn.execute("PRAGMA busy_timeout=5000;")
		try:
			conn.execute("PRAGMA journal_mode=WAL;")
		except sqlite3.OperationalError:
			pass
		conn.row_factory = sqlite3.Row
		yield conn
	finally:
		conn.close()


class SessionRegistry:
	"""Acceso a `session.db` (WAL + busy_timeout). Schema owned by Python."""

	def __init__(self, db_path: Optional[str] = None):
		self.db_path = str(db_path) if db_path else str(get_session_db())
		self._init_db()

	@contextmanager
	def _connect(self) -> Iterator[sqlite3.Connection]:
		with connect_session_db(self.db_path) as conn:
			yield conn

	def _init_db(self) -> None:
		from pathlib import Path

		Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
		with self._connect() as conn:
			# Migración del esquema PRE-RELEASE del slice (commit 9a48e1e): la tabla
			# vieja no tiene `event_seq` y dejaba al lector en "no such column".
			# Nunca se desplegó; se recrea. A partir de aquí manda `user_version`.
			has_table = conn.execute(
				"SELECT 1 FROM sqlite_master WHERE type='table' AND name='mission_events'"
			).fetchone()
			if has_table:
				cols = {row[1] for row in conn.execute("PRAGMA table_info(mission_events)").fetchall()}
				if "event_seq" not in cols:
					conn.execute("DROP TABLE mission_events")
			conn.executescript(_SCHEMA)
			registry_cols = {row[1] for row in conn.execute("PRAGMA table_info(session_registry)").fetchall()}
			if "last_seen_event_seq" not in registry_cols:
				# v3: cursor de eventos para el digest (BD creada antes de v3).
				# El ALTER no es atómico: dos sesiones abriendo a la vez pueden chocar.
				try:
					conn.execute("ALTER TABLE session_registry ADD COLUMN last_seen_event_seq INTEGER NOT NULL DEFAULT 0")
				except sqlite3.OperationalError:
					pass
			current = conn.execute("PRAGMA user_version").fetchone()[0]
			if current < 2:
				# v2: el trigger `no_replace` también cubre `event_seq`. En BD ya
				# inicializadas con v1, `CREATE TRIGGER IF NOT EXISTS` no lo actualiza.
				conn.execute("DROP TRIGGER IF EXISTS mission_events_no_replace")
				conn.executescript(_SCHEMA)
			if current < 3:
				conn.execute("PRAGMA user_version=3")
			if current < 4:
				# v4: espejo canónico de turnos (`session_mirror`). `_SCHEMA` ya la
				# crea idempotentemente; aquí solo se sella la versión.
				conn.execute("PRAGMA user_version=4")
			conn.commit()

	# ── Lecturas ────────────────────────────────────────────────────────────
	def get_by_originator(self, originator: str) -> Optional[dict]:
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM session_registry WHERE originator = ?", (originator,)).fetchone()
		return dict(row) if row else None

	def get_by_continuity(self, continuity_id: str) -> List[dict]:
		with self._connect() as conn:
			rows = conn.execute(
				"SELECT * FROM session_registry WHERE continuity_id = ? ORDER BY updated_at DESC",
				(continuity_id,),
			).fetchall()
		return [dict(r) for r in rows]

	def list_sessions(self, limit: int = 500) -> List[dict]:
		"""Todas las filas del registro, más recientes primero (alimenta el tablón).

		El tablón (`session_board`) es una VISTA del registro: lee de aquí y usa los
		latidos de liveness solo como señal de "vivo/activo" (F2)."""
		with self._connect() as conn:
			rows = conn.execute(
				"SELECT * FROM session_registry ORDER BY updated_at DESC LIMIT ?",
				(int(limit),),
			).fetchall()
		return [dict(r) for r in rows]

	# ── Escrituras ──────────────────────────────────────────────────────────
	def upsert_session(
		self,
		*,
		originator: str,
		continuity_id: str,
		mission_id: str,
		campaign_id: Optional[str] = None,
		role: str = "task",
		lineage_id: Optional[str] = None,
		affinity: Any = None,
		branch: Optional[str] = None,
		worktree: Optional[str] = None,
		head_commit: Optional[str] = None,
		title: Optional[str] = None,
		intent: Optional[str] = None,
		last_seen_global_turn: int = 0,
		last_seen_event_seq: int = 0,
	) -> None:
		"""UPSERT por `originator` (el leg). Política UNIFICADA "primer enlace gana por
		cuerpo" (F5): el `continuity_id` YA atado se conserva SIEMPRE — este es el
		único escritor con la invariante atómica (el hook del arnés usa la MISMA
		cláusula `ON CONFLICT ... SET continuity_id=session_registry.continuity_id`).
		`mission_id`/`updated_at`/afinidad sí se refrescan (el alma no se reescribe).
	Un leg vuelto a ver tras `unregister_session` se reactiva (`ttl_state=active`)."""
		provider, session_id = _split_originator(originator)
		affinity_json = json.dumps(canonize_affinity(affinity or []), ensure_ascii=False)
		now = time.time()
		with self._connect() as conn:
			conn.execute(
				"""
				INSERT INTO session_registry (
					originator, continuity_id, mission_id, campaign_id, role, lineage_id,
					provider, session_id, last_seen_global_turn, last_seen_event_seq,
					affinity_json, updated_at, branch, worktree, head_commit, title, intent
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(originator) DO UPDATE SET
					continuity_id = session_registry.continuity_id,
					mission_id = excluded.mission_id,
					campaign_id = excluded.campaign_id,
					role = excluded.role,
					lineage_id = excluded.lineage_id,
					provider = excluded.provider,
					session_id = excluded.session_id,
					last_seen_global_turn = excluded.last_seen_global_turn,
					last_seen_event_seq = excluded.last_seen_event_seq,
					affinity_json = excluded.affinity_json,
					updated_at = excluded.updated_at,
					branch = COALESCE(excluded.branch, session_registry.branch),
					worktree = COALESCE(excluded.worktree, session_registry.worktree),
					head_commit = COALESCE(excluded.head_commit, session_registry.head_commit),
					title = COALESCE(excluded.title, session_registry.title),
					intent = COALESCE(excluded.intent, session_registry.intent),
					ttl_state = 'active'
				""",
				(
					originator,
					continuity_id,
					mission_id,
					campaign_id,
					role,
					lineage_id,
					provider,
					session_id,
					last_seen_global_turn,
					last_seen_event_seq,
					affinity_json,
					now,
					branch,
					worktree,
					head_commit,
					title,
					intent,
				),
			)
			conn.commit()

	def next_global_turn(self, originator: str, affinity: Any = None) -> int:
		"""Inserta un turno en el reloj y devuelve su `global_turn` monotónico."""
		affinity_json = json.dumps(canonize_affinity(affinity or []), ensure_ascii=False)
		with self._connect() as conn:
			cur = conn.execute(
				"INSERT INTO global_turn_seq (created_at, originator, affinity_json) VALUES (?, ?, ?)",
				(time.time(), originator, affinity_json),
			)
			conn.commit()
			return int(cur.lastrowid or 0)

	def get_max_global_turn(self) -> int:
		with self._connect() as conn:
			row = conn.execute("SELECT MAX(global_turn) AS m FROM global_turn_seq").fetchone()
		return int(row["m"]) if row and row["m"] is not None else 0

	def get_max_event_seq(self) -> int:
		"""Último `event_seq` global (cursor del digest; 0 si no hay eventos)."""
		with self._connect() as conn:
			row = conn.execute("SELECT MAX(event_seq) AS m FROM mission_events").fetchone()
		return int(row["m"]) if row and row["m"] is not None else 0

	def active_continuities(self) -> List[str]:
		"""Almas con al menos un leg NO expirado (para retención del espejo)."""
		with self._connect() as conn:
			rows = conn.execute(
				"SELECT DISTINCT continuity_id FROM session_registry WHERE ttl_state != 'expired'"
			).fetchall()
		return [str(row["continuity_id"]) for row in rows if row["continuity_id"]]

	def divergent_turns(
		self,
		since_global_turn: int,
		*,
		viewer_originator: str,
		viewer_affinity: Optional[List[str]] = None,
		limit: int = 20,
		allow_all: bool = False,
	) -> List[dict]:
		"""Turnos del reloj posteriores a tu marca, con filtro D15 (deny-by-default).

		Incluye SIEMPRE los tuyos; los ajenos solo si su afinidad intersecta la tuya
		(o `allow_all`, que exige flag de operador). `content` se rellena únicamente
		desde turnos del espejo con `global_turn > 0` (el backfill histórico no tiene
		reloj: no se inventa).
		"""
		from red_pill.core.affinity import canonize_affinity

		since = max(0, int(since_global_turn or 0))
		cap = max(1, min(int(limit or 20), 200))
		mine = sorted(set(canonize_affinity(viewer_affinity or [])))
		# D15 se filtra EN SQL (json_each) para no sufrir starvation: un LIMIT
		# calculado en Python podía devolver vacío con miles de turnos ajenos.
		where = ["g.global_turn > ?"]
		params: List[Any] = [since]
		if not allow_all:
			if mine:
				marks = ",".join("?" * len(mine))
				where.append(
					"(g.originator = ? OR EXISTS (SELECT 1 FROM json_each(g.affinity_json) je "
					f"WHERE lower(trim(je.value)) IN ({marks})))"
				)
				params.append(viewer_originator)
				params.extend(mine)
			else:
				where.append("g.originator = ?")
				params.append(viewer_originator)
		sql = (
			"SELECT g.global_turn, g.created_at, g.originator, g.affinity_json, "
			"r.mission_id, r.continuity_id, r.role, r.ttl_state "
			"FROM global_turn_seq g LEFT JOIN session_registry r ON r.originator = g.originator "
			"WHERE " + " AND ".join(where) + " ORDER BY g.global_turn ASC LIMIT ?"
		)
		params.append(cap)
		with self._connect() as conn:
			rows = conn.execute(sql, tuple(params)).fetchall()
			selected: List[dict] = []
			for row in rows:
				origin = str(row["originator"] or "")
				try:
					theirs = set(json.loads(row["affinity_json"] or "[]"))
				except Exception:
					theirs = set()
				item = {
					"global_turn": int(row["global_turn"]),
					"created_at": float(row["created_at"] or 0.0),
					"originator": origin,
					"mission_id": row["mission_id"],
					"continuity_id": row["continuity_id"],
					"role": row["role"],
					"ttl_state": row["ttl_state"],
					"affinity": sorted(theirs),
					"turns": [],
				}
				content_rows = conn.execute(
					"SELECT role, content, tool_calls, tool_call_id, model, ts FROM session_mirror "
					"WHERE originator = ? AND global_turn = ? ORDER BY seq ASC",
					(origin, int(row["global_turn"])),
				).fetchall()
				for turn in content_rows:
					try:
						calls = json.loads(turn["tool_calls"]) if turn["tool_calls"] else None
					except json.JSONDecodeError:
						calls = None
					if not isinstance(calls, list):
						calls = None
					item["turns"].append(
						{
							"role": turn["role"],
							"content": turn["content"],
							"tool_calls": calls,
							"tool_call_id": turn["tool_call_id"],
							"model": turn["model"],
							"ts": turn["ts"],
						}
					)
				selected.append(item)
				if len(selected) >= cap:
					break
		return selected

	# ── Eventos de misión (Fase 2, append-only) ─────────────────────────────
	def add_event(
		self,
		*,
		event_type: str,
		mission_id: str,
		summary: str,
		campaign_id: Optional[str] = None,
		continuity_id: Optional[str] = None,
		originator: Optional[str] = None,
		global_turn: int = 0,
		ref: Optional[str] = None,
		sealed: bool = False,
	) -> dict:
		"""Publica un evento de misión. `ValueError` si tipo/misión/summary no valen.

		`summary`/`ref` se sanean (una línea, sin controles/ANSI, sin `<>`) y se
		recortan. `sealed` es estricto (`is True`): visible solo para su misión.
		Devuelve el evento con `event_seq` (el cursor real; `global_turn` es solo la
		referencia del turno).
		"""
		import uuid as _uuid

		if not isinstance(sealed, bool):
			raise ValueError("sealed debe ser boolean")
		kind = str(event_type or "").strip()
		if kind not in EVENT_TYPES:
			raise ValueError(f"tipo de evento desconocido: {event_type!r}")
		mission = _clean_key(mission_id)
		if not mission:
			raise ValueError("mission_id requerido")
		campaign = _clean_key(campaign_id) if campaign_id else None
		continuity = _clean_key(continuity_id) if continuity_id else None
		orig = _clean_key(originator) if originator else None
		text = _clean_text(summary, _EVENT_SUMMARY_MAX)
		if not text:
			raise ValueError("summary requerido")
		ref_clean = _clean_text(ref, _EVENT_REF_MAX) if ref else None
		event_id = _uuid.uuid4().hex
		now = time.time()
		with self._connect() as conn:
			if orig:
				recent = conn.execute(
					"SELECT COUNT(*) AS n FROM mission_events WHERE mission_id = ? AND originator = ? AND created_at > ?",
					(mission, orig, now - 60.0),
				).fetchone()
				if recent and int(recent["n"]) >= _EVENT_RATE_PER_MIN:
					raise ValueError(f"rate limit: más de {_EVENT_RATE_PER_MIN} eventos/min para {orig}")
			cur = conn.execute(
				"""
				INSERT INTO mission_events (
					event_id, type, mission_id, campaign_id, continuity_id, originator,
					global_turn, summary, ref, sealed, created_at
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(
					event_id,
					kind,
					mission,
					campaign,
					continuity,
					orig,
					int(global_turn or 0),
					text,
					ref_clean,
					1 if sealed is True else 0,
					now,
				),
			)
			conn.commit()
			seq = int(cur.lastrowid or 0)
		return {
			"event_seq": seq,
			"event_id": event_id,
			"type": kind,
			"mission_id": mission,
			"campaign_id": campaign,
			"continuity_id": continuity,
			"originator": orig,
			"global_turn": int(global_turn or 0),
			"summary": text,
			"ref": ref_clean,
			"sealed": sealed is True,
			"created_at": now,
		}

	def fetch_events(
		self,
		mission_id: str,
		*,
		since_seq: int = 0,
		types: Optional[List[str]] = None,
		limit: int = 50,
		viewer_originator: Optional[str] = None,
	) -> List[dict]:
		"""Eventos de `mission_id` con `event_seq > since_seq` (asc), con tope.

		El cursor es `event_seq` (no `global_turn`: varios eventos comparten turno y
		se perderían). `sealed` se filtra EN SQL: solo lo ve el **mismo originator**
		que lo publicó (antes del LIMIT: no consume cupo ni revela existencia).
		La misión/visor se normalizan con la MISMA `_clean_key` que al escribir.
		"""
		mission = _clean_key(mission_id)
		if not mission:
			return []
		params: list = [mission]
		sql = "SELECT * FROM mission_events WHERE mission_id = ?"
		since = int(since_seq or 0)
		if since > 0:
			sql += " AND event_seq > ?"
			params.append(since)
		sql += " AND (sealed = 0 OR ? = originator)"
		params.append(_clean_key(viewer_originator) if viewer_originator else "")
		if types:
			if not isinstance(types, (list, tuple)):
				raise ValueError("types debe ser una lista")
			known = [str(t) for t in types]
			unknown = [t for t in known if t not in EVENT_TYPES]
			if unknown:
				raise ValueError(f"tipos desconocidos: {unknown!r}")
			sql += " AND type IN (" + ",".join("?" * len(known)) + ")"
			params.extend(known)
		sql += " ORDER BY event_seq ASC LIMIT ?"
		params.append(max(1, min(int(limit or 50), 500)))
		with self._connect() as conn:
			rows = conn.execute(sql, tuple(params)).fetchall()
		out: List[dict] = []
		for row in rows:
			event = dict(row)
			event["sealed"] = bool(event.get("sealed"))
			out.append(event)
		return out

	def count_events(
		self,
		mission_id: str,
		*,
		since_seq: int = 0,
		until_seq: Optional[int] = None,
		types: Optional[List[str]] = None,
		viewer_originator: Optional[str] = None,
	) -> int:
		"""Nº de eventos VISIBLES para `viewer_originator` desde `since_seq` (digest)."""
		mission = _clean_key(mission_id)
		if not mission:
			return 0
		params: list = [mission]
		sql = "SELECT COUNT(*) AS n FROM mission_events WHERE mission_id = ?"
		since = int(since_seq or 0)
		if since > 0:
			sql += " AND event_seq > ?"
			params.append(since)
		if until_seq is not None:
			sql += " AND event_seq <= ?"
			params.append(int(until_seq))
		sql += " AND (sealed = 0 OR ? = originator)"
		params.append(_clean_key(viewer_originator) if viewer_originator else "")
		if types:
			if not isinstance(types, (list, tuple)):
				raise ValueError("types debe ser una lista")
			known = [str(t) for t in types]
			unknown = [t for t in known if t not in EVENT_TYPES]
			if unknown:
				raise ValueError(f"tipos desconocidos: {unknown!r}")
			sql += " AND type IN (" + ",".join("?" * len(known)) + ")"
			params.extend(known)
		with self._connect() as conn:
			row = conn.execute(sql, tuple(params)).fetchone()
		return int(row["n"]) if row else 0

	def set_last_seen_event_seq(self, originator: str, seq: int) -> None:
		"""Fija el cursor del digest DESPUÉS de calcularlo (nunca antes)."""
		with self._connect() as conn:
			conn.execute(
				"UPDATE session_registry SET last_seen_event_seq = ? WHERE originator = ?",
				(int(seq), str(originator or "")),
			)
			conn.commit()

	# ── Ciclo de vida del leg (D14) ─────────────────────────────────────────
	def unregister_session(self, originator: str) -> bool:
		"""Expira EXPLÍCITAMENTE un leg (cierre de sesión); `True` si existía.

		Marca `ttl_state='expired'` y sella `updated_at` para que la purga D14
		cuente el plazo desde el cierre. El tablón deja de mostrarlo de inmediato.
		"""
		origin = str(originator or "").strip()
		if not origin:
			return False
		with self._connect() as conn:
			cur = conn.execute(
				"UPDATE session_registry SET ttl_state = 'expired', ttl_checked_at = ?, updated_at = ? WHERE originator = ?",
				(time.time(), time.time(), origin),
			)
			conn.commit()
			return bool(cur.rowcount)

	def purge_expired(self, after_s: Optional[float] = None) -> int:
		"""Purga D14: borra legs expirados hace más de `after_s` (default config).

		`MULTISESSION_PURGE_AFTER_SECS` (24h). Nunca toca filas activas ni
		`mission_events` (su TTL es la vida de la misión, no la presencia).
		`VACUUM` best-effort: no puede correr dentro de una transacción.
		"""
		import red_pill.config as cfg

		window = float(after_s) if after_s is not None else float(getattr(cfg.get_config(), "MULTISESSION_PURGE_AFTER_SECS", 86400))
		cutoff = time.time() - max(0.0, window)
		with self._connect() as conn:
			cur = conn.execute(
				"DELETE FROM session_registry WHERE ttl_state = 'expired' AND updated_at < ?",
				(cutoff,),
			)
			conn.commit()
			removed = int(cur.rowcount or 0)
			if removed:
				try:
					conn.execute("VACUUM")
				except sqlite3.OperationalError:
					pass
		return removed
