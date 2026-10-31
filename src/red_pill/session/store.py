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
import os
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
created_at REAL NOT NULL,
to_continuity TEXT,
verb TEXT,
thread_id TEXT,
hop INTEGER,
hop_max INTEGER,
expects_reply INTEGER,
value_class TEXT,
expires_at REAL
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
source_ref TEXT,
-- turn_id: identidad PROPIA del turno (sellada por el kernel, no por el arnés).
-- `request_id` se conserva como procedencia (de dónde vino), no como identidad.
turn_id TEXT,
status TEXT NOT NULL DEFAULT 'completed',
request_id TEXT,
status_reason TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mirror_seq ON session_mirror(continuity_id, seq);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mirror_source ON session_mirror(continuity_id, originator, source_ref)
WHERE source_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mirror_ts ON session_mirror(continuity_id, ts);

CREATE TABLE IF NOT EXISTS session_compactions (
compaction_id TEXT PRIMARY KEY,
continuity_id TEXT NOT NULL,
mission_id TEXT NOT NULL,
parent_compaction_id TEXT,
range_start_seq INTEGER NOT NULL,
range_end_seq INTEGER NOT NULL,
summary TEXT NOT NULL,
model TEXT,
status TEXT NOT NULL DEFAULT 'completed',
reason TEXT,
tokens_before INTEGER,
tokens_after INTEGER,
created_at REAL NOT NULL,
completed_at REAL
);

CREATE INDEX IF NOT EXISTS idx_compactions_latest ON session_compactions(continuity_id, status, range_end_seq DESC);
CREATE INDEX IF NOT EXISTS idx_compactions_parent ON session_compactions(parent_compaction_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_compactions_range ON session_compactions(continuity_id, range_start_seq, range_end_seq) WHERE status != 'aborted';

CREATE TABLE IF NOT EXISTS session_leases (
lease_key TEXT PRIMARY KEY,
scope TEXT NOT NULL,
subject_id TEXT NOT NULL,
continuity_id TEXT NOT NULL,
mission_id TEXT,
holder_originator TEXT NOT NULL DEFAULT '',
owner_kind TEXT NOT NULL,
state TEXT NOT NULL DEFAULT 'active',
started_at REAL NOT NULL,
last_heartbeat_at REAL NOT NULL,
idle_ttl_s INTEGER NOT NULL,
max_wall_s INTEGER NOT NULL,
extended_by TEXT,
reason TEXT,
metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_leases_heartbeat ON session_leases(state, last_heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_leases_scope ON session_leases(scope, subject_id, state);
CREATE INDEX IF NOT EXISTS idx_leases_continuity ON session_leases(continuity_id, state);

CREATE TABLE IF NOT EXISTS dynamic_decisions (
decision_id TEXT PRIMARY KEY,
subject_event_id TEXT NOT NULL,
mission_id TEXT NOT NULL,
claim TEXT NOT NULL,
evidence TEXT,
severity TEXT NOT NULL DEFAULT 'low',
proposed_action TEXT NOT NULL DEFAULT 'flag',
state TEXT NOT NULL DEFAULT 'open',
owner TEXT,
created_by TEXT NOT NULL,
created_at REAL NOT NULL,
expires_at REAL,
requires_operator INTEGER NOT NULL DEFAULT 0,
resolved_at REAL,
resolution_reason TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_decisions_unique ON dynamic_decisions(subject_event_id, created_by);
CREATE INDEX IF NOT EXISTS idx_decisions_state ON dynamic_decisions(mission_id, state);
CREATE INDEX IF NOT EXISTS idx_decisions_subject ON dynamic_decisions(subject_event_id, state);

CREATE TABLE IF NOT EXISTS note_status (
event_id TEXT PRIMARY KEY,
mission_id TEXT NOT NULL,
status TEXT NOT NULL DEFAULT 'visible',
updated_at REAL NOT NULL,
updated_by TEXT,
reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_note_status_mission ON note_status(mission_id, status);

CREATE TABLE IF NOT EXISTS decision_suggestions (
id INTEGER PRIMARY KEY AUTOINCREMENT,
decision_id TEXT NOT NULL,
reviewer_continuity_id TEXT NOT NULL,
verdict TEXT NOT NULL,
confidence TEXT NOT NULL,
reason TEXT,
created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_suggestions_decision ON decision_suggestions(decision_id, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_reviews (
job_id TEXT PRIMARY KEY,
decision_id TEXT NOT NULL,
reviewer_continuity_id TEXT NOT NULL,
mode TEXT NOT NULL,
confidence TEXT,
created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_decision ON decision_reviews(decision_id, created_at DESC);
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
		# v8 (AD-095): correspondencia entre almas. Un solo tipo para los cuatro
		# verbos: el verbo es columna, no tipo (si no, cada verbo migra la taxonomía).
		"message",
		# Internos de D23-SCORE (D-obj): solo los escribe el store, no el modelo.
		"decision_opened",
		"decision_upheld",
		"decision_dismissed",
		"decision_escalated",
		"decision_moderated",
		"decision_suggested",
	}
)

# Auditoría interna de D23-SCORE: se escribe en `mission_events`, pero no se
# renderiza en el tablón/digest (la vista pública es la nota + su estado).
_INTERNAL_EVENT_TYPES = frozenset(
	{
		"decision_opened",
		"decision_upheld",
		"decision_dismissed",
		"decision_escalated",
		"decision_moderated",
		"decision_suggested",
	}
)

_EVENT_SUMMARY_MAX = 800
_EVENT_REF_MAX = 400

# v8 (AD-095): verbos de correspondencia (D-02/D-12) y naturaleza del valor
# (aportación de la hermana en E-002: el TTL no es solo tiempo, es tipo de valor).
_MESSAGE_VERBS = frozenset({"notify", "ask", "reply", "park"})
_MESSAGE_VALUES = frozenset({"now", "seed"})
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
		if db_path != ":memory:":
			try:
				os.chmod(db_path, 0o600)
			except OSError:
				pass
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
			has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mission_events'").fetchone()
			if has_table:
				cols = {row[1] for row in conn.execute("PRAGMA table_info(mission_events)").fetchall()}
				if "event_seq" not in cols:
					conn.execute("DROP TABLE mission_events")
			conn.executescript(_SCHEMA)
			mirror_cols = {row[1] for row in conn.execute("PRAGMA table_info(session_mirror)").fetchall()}
			if "status" not in mirror_cols:
				conn.execute("ALTER TABLE session_mirror ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
			if "request_id" not in mirror_cols:
				conn.execute("ALTER TABLE session_mirror ADD COLUMN request_id TEXT")
			if "status_reason" not in mirror_cols:
				conn.execute("ALTER TABLE session_mirror ADD COLUMN status_reason TEXT")
			try:
				conn.execute("ALTER TABLE session_mirror ADD COLUMN turn_id TEXT")
			except sqlite3.OperationalError:
				pass  # ya existe
			conn.execute("CREATE INDEX IF NOT EXISTS idx_mirror_request ON session_mirror(continuity_id, request_id)")
			conn.execute("CREATE INDEX IF NOT EXISTS idx_mirror_status ON session_mirror(continuity_id, status)")
			registry_cols = {row[1] for row in conn.execute("PRAGMA table_info(session_registry)").fetchall()}
			if "last_seen_event_seq" not in registry_cols:
				# v3: cursor de eventos para el digest (BD creada antes de v3).
				# El ALTER no es atómico: dos sesiones abriendo a la vez pueden chocar.
				try:
					conn.execute("ALTER TABLE session_registry ADD COLUMN last_seen_event_seq INTEGER NOT NULL DEFAULT 0")
				except sqlite3.OperationalError:
					pass
			# D23-SCORE v0.1: confianza del revisor en jobs semi/auto.
			review_cols = {row[1] for row in conn.execute("PRAGMA table_info(decision_reviews)").fetchall()}
			if review_cols and "confidence" not in review_cols:
				try:
					conn.execute("ALTER TABLE decision_reviews ADD COLUMN confidence TEXT")
				except sqlite3.OperationalError:
					pass
			# Una sugerencia por (D-obj, revisor): sin spam de filas; la última
			# reemplaza a la anterior y el evento solo se emite si cambia.
			conn.execute(
				"DELETE FROM decision_suggestions WHERE id NOT IN ("
				"SELECT MAX(id) FROM decision_suggestions GROUP BY decision_id, reviewer_continuity_id)"
			)
			conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_reviewer ON decision_suggestions(decision_id, reviewer_continuity_id)")
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
			if current < 5:
				# v5: estado de turno (B-01s): pending/completed/aborted + request_id.
				conn.execute("PRAGMA user_version=5")
			if current < 6:
				# v6: compactaciones de contexto (B-02): rangos, resumen y linaje.
				conn.execute("PRAGMA user_version=6")
			if current < 7:
				# v7: leases de trabajo y misión (B-01L/RFC-INTEROP-003).
				conn.execute("PRAGMA user_version=7")
			if current < 8:
				# v8 (AD-095): correspondencia entre almas. El destinatario vive en
				# el EVENTO (una sola verdad, append-only); el buzón guarda solo su
				# estado de entrega. `_SCHEMA` ya crea las columnas en BD nuevas.
				cols = {row[1] for row in conn.execute("PRAGMA table_info(mission_events)").fetchall()}
				for name, decl in (
					("to_continuity", "TEXT"),
					("verb", "TEXT"),
					("thread_id", "TEXT"),
					("hop", "INTEGER"),
					("hop_max", "INTEGER"),
					("expects_reply", "INTEGER"),
					("value_class", "TEXT"),
					("expires_at", "REAL"),
				):
					if name not in cols:
						try:
							conn.execute(f"ALTER TABLE mission_events ADD COLUMN {name} {decl}")
						except sqlite3.OperationalError:
							pass
				conn.execute("CREATE INDEX IF NOT EXISTS idx_events_inbox ON mission_events(to_continuity, event_seq)")
				conn.execute("PRAGMA user_version=8")
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
	def _upsert_session_conn(
		self,
		conn: sqlite3.Connection,
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
		provider, session_id = _split_originator(originator)
		affinity_json = json.dumps(canonize_affinity(affinity or []), ensure_ascii=False)
		now = time.time()
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
				lineage_id = COALESCE(excluded.lineage_id, session_registry.lineage_id),
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
		with self._connect() as conn:
			self._upsert_session_conn(
				conn,
				originator=originator,
				continuity_id=continuity_id,
				mission_id=mission_id,
				campaign_id=campaign_id,
				role=role,
				lineage_id=lineage_id,
				affinity=affinity,
				branch=branch,
				worktree=worktree,
				head_commit=head_commit,
				title=title,
				intent=intent,
				last_seen_global_turn=last_seen_global_turn,
				last_seen_event_seq=last_seen_event_seq,
			)
			conn.commit()

	def activate_leg(
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
		"""Cierra otros legs activos del alma y activa este, en UNA transacción.

		La migración de cuerpo no puede dejar dos legs activos por un lock o un
		fallo intermedio: el cierre y el upsert comparten `BEGIN IMMEDIATE`.
		"""
		now = time.time()
		with self._connect() as conn:
			conn.execute("BEGIN IMMEDIATE")
			if lineage_id is None:
				row = conn.execute(
					"SELECT lineage_id FROM session_registry WHERE continuity_id=? AND lineage_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
					(continuity_id,),
				).fetchone()
				if row and row["lineage_id"]:
					lineage_id = str(row["lineage_id"])
			conn.execute(
				"UPDATE session_registry SET ttl_state='expired', ttl_checked_at=?, updated_at=? "
				"WHERE continuity_id=? AND originator<>? AND ttl_state='active'",
				(now, now, continuity_id, originator),
			)
			self._upsert_session_conn(
				conn,
				originator=originator,
				continuity_id=continuity_id,
				mission_id=mission_id,
				campaign_id=campaign_id,
				role=role,
				lineage_id=lineage_id,
				affinity=affinity,
				branch=branch,
				worktree=worktree,
				head_commit=head_commit,
				title=title,
				intent=intent,
				last_seen_global_turn=last_seen_global_turn,
				last_seen_event_seq=last_seen_event_seq,
			)
			conn.commit()

	def next_global_turn(self, originator: str, affinity: Any = None) -> int:
		"""Inserta un turno en el reloj y devuelve su `global_turn` monotónico.

		Delega en `session.turn_seal`, que es el **único** punto que avanza el
		reloj: `BEGIN IMMEDIATE` (lock de escritura antes de leer) + relectura del
		máximo, para que dos escritores concurrentes no repartan el mismo número ni
		hagan retroceder el contador en WAL.
		"""
		from red_pill.session.turn_seal import next_global_turn as _next

		return _next(str(originator or ""), affinity, db_path=self.db_path)

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
			rows = conn.execute("SELECT DISTINCT continuity_id FROM session_registry WHERE ttl_state != 'expired'").fetchall()
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
				where.append(f"(g.originator = ? OR EXISTS (SELECT 1 FROM json_each(g.affinity_json) je WHERE lower(trim(je.value)) IN ({marks})))")
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
		to_continuity: Optional[str] = None,
		verb: Optional[str] = None,
		thread_id: Optional[str] = None,
		hop: Optional[int] = None,
		hop_max: Optional[int] = None,
		expects_reply: Optional[bool] = None,
		value_class: Optional[str] = None,
		expires_at: Optional[float] = None,
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
		# v8 (AD-095): correspondencia. `verb` sin destinatario (o al revés) es un
		# error del llamante, no un evento raro: fail-closed antes de escribir.
		to_soul = _clean_key(to_continuity) if to_continuity else None
		verb_clean = str(verb or "").strip().lower() or None
		if verb_clean and verb_clean not in _MESSAGE_VERBS:
			raise ValueError(f"verbo desconocido: {verb!r}")
		if verb_clean and not to_soul:
			raise ValueError("un mensaje necesita destinatario (`to_continuity`)")
		if verb_clean and kind != "message":
			raise ValueError("un mensaje es type='message'")
		if kind == "message" and not verb_clean:
			raise ValueError("type='message' exige verbo (notify|ask|reply|park)")
		thread = _clean_key(thread_id) if thread_id else None
		hop_n = max(0, int(hop or 0)) if verb_clean else None
		hop_max_n = max(0, int(hop_max or 0)) if verb_clean else None
		expects = None if expects_reply is None else (1 if expects_reply else 0)
		value = str(value_class or "now").strip().lower() if verb_clean else None
		if value is not None and value not in _MESSAGE_VALUES:
			raise ValueError(f"value_class desconocido: {value_class!r}")
		expires = float(expires_at) if expires_at else None
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
					global_turn, summary, ref, sealed, created_at,
					to_continuity, verb, thread_id, hop, hop_max, expects_reply,
					value_class, expires_at
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
					to_soul,
					verb_clean,
					thread,
					hop_n,
					hop_max_n,
					expects,
					value,
					expires,
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
			"to_continuity": to_soul,
			"verb": verb_clean,
			"thread_id": thread,
			"hop": hop_n,
			"hop_max": hop_max_n,
			"expects_reply": None if expects is None else bool(expects),
			"value_class": value,
			"expires_at": expires,
		}

	def fetch_events(
		self,
		mission_id: str,
		*,
		since_seq: int = 0,
		types: Optional[List[str]] = None,
		limit: int = 50,
		viewer_originator: Optional[str] = None,
		viewer_continuity_id: Optional[str] = None,
		include_hidden: bool = False,
	) -> List[dict]:
		"""Eventos de `mission_id` con `event_seq > since_seq` (asc), con tope.

		El cursor es `event_seq` (no `global_turn`: varios eventos comparten turno y
		se perderían). `sealed` se filtra EN SQL: solo lo ve el **mismo originator**
		que lo publicó (antes del LIMIT: no consume cupo ni revela existencia).
		`hidden/retracted` (D23-SCORE) se filtran antes del LIMIT salvo para su
		autor o para el Operador (`include_hidden`). Cada evento trae `note_status`
		y `open_decisions`.
		"""
		mission = _clean_key(mission_id)
		if not mission:
			return []
		params: list = [mission]
		sql = (
			"SELECT e.*, COALESCE(ns.status, 'visible') AS note_status "
			"FROM mission_events e LEFT JOIN note_status ns ON ns.event_id = e.event_id "
			"WHERE e.mission_id = ?"
		)
		since = int(since_seq or 0)
		if since > 0:
			sql += " AND e.event_seq > ?"
			params.append(since)
		sql += " AND (e.sealed = 0 OR ? = e.originator)"
		params.append(_clean_key(viewer_originator) if viewer_originator else "")
		sql += " AND (COALESCE(ns.status, 'visible') NOT IN ('hidden', 'retracted') OR ? = 1 OR e.continuity_id = ?)"
		params.extend([1 if include_hidden else 0, _clean_key(viewer_continuity_id) if viewer_continuity_id else ""])
		sql += " AND e.type NOT IN ('decision_opened', 'decision_upheld', 'decision_dismissed', 'decision_escalated', 'decision_moderated', 'decision_suggested')"
		# v8 (AD-095): la correspondencia NO se renderiza en el tablón de la misión.
		# Solo la ve su destinatario (también por `inbox`) y quien la escribió.
		viewer_soul = _clean_key(viewer_continuity_id) if viewer_continuity_id else ""
		sql += " AND (e.to_continuity IS NULL OR e.to_continuity = ? OR e.continuity_id = ?)"
		params.extend([viewer_soul, viewer_soul])
		if types:
			if not isinstance(types, (list, tuple)):
				raise ValueError("types debe ser una lista")
			known = [str(t) for t in types]
			unknown = [t for t in known if t not in EVENT_TYPES]
			if unknown:
				raise ValueError(f"tipos desconocidos: {unknown!r}")
			sql += " AND e.type IN (" + ",".join("?" * len(known)) + ")"
			params.extend(known)
		sql += " ORDER BY e.event_seq ASC LIMIT ?"
		params.append(max(1, min(int(limit or 50), 500)))
		with self._connect() as conn:
			rows = conn.execute(sql, tuple(params)).fetchall()
			out: List[dict] = []
			for row in rows:
				event = dict(row)
				event["sealed"] = bool(event.get("sealed"))
				event["note_status"] = str(event.get("note_status") or "visible")
				event["open_decisions"] = 0
				out.append(event)
			ids = [e["event_id"] for e in out]
			if ids:
				counts = conn.execute(
					"SELECT subject_event_id, COUNT(*) AS n FROM dynamic_decisions "
					"WHERE state IN ('open', 'escalated') AND subject_event_id IN (" + ",".join("?" * len(ids)) + ") GROUP BY subject_event_id",
					tuple(ids),
				).fetchall()
				by_id = {str(row["subject_event_id"]): int(row["n"]) for row in counts}
				for event in out:
					event["open_decisions"] = by_id.get(event["event_id"], 0)
		return out

	def fetch_inbox(
		self,
		continuity_id: str,
		*,
		limit: int = 50,
		since_seq: int = 0,
		include_expired: bool = False,
	) -> List[dict]:
		"""Mensajes dirigidos a `continuity_id` (AD-095), de cualquier misión.

		La correspondencia **no** se lee por misión: se lee por alma. Un mensaje
		vive en el tablón de quien lo escribió (append-only) y el destinatario lo
		encuentra por su dirección, igual que el cartero no imprime el periódico.
		`sealed` y `hidden/retracted` se excluyen: un mensaje sellado no tiene
		destinatario posible, y la moderación ya lo apartó.
		"""
		soul = _clean_key(continuity_id)
		if not soul:
			return []
		params: list = [soul]
		sql = (
			"SELECT e.*, COALESCE(ns.status, 'visible') AS note_status "
			"FROM mission_events e LEFT JOIN note_status ns ON ns.event_id = e.event_id "
			"WHERE e.to_continuity = ? AND e.sealed = 0"
			" AND COALESCE(ns.status, 'visible') NOT IN ('hidden', 'retracted')"
		)
		since = int(since_seq or 0)
		if since > 0:
			sql += " AND e.event_seq > ?"
			params.append(since)
		if not include_expired:
			sql += " AND (e.expires_at IS NULL OR e.expires_at > ?)"
			params.append(time.time())
		sql += " ORDER BY e.event_seq ASC LIMIT ?"
		params.append(max(1, min(int(limit or 50), 200)))
		with self._connect() as conn:
			rows = conn.execute(sql, tuple(params)).fetchall()
		out: List[dict] = []
		for row in rows:
			event = dict(row)
			event["sealed"] = bool(event.get("sealed"))
			event["expects_reply"] = None if event.get("expects_reply") is None else bool(event.get("expects_reply"))
			event["note_status"] = str(event.get("note_status") or "visible")
			out.append(event)
		return out

	def event_exists(self, *, mission_id: str, event_type: str, ref: str, summary: str) -> bool:
		"""Idempotencia de eventos de job (S2): misma señal, mismo ref/summary."""
		with self._connect() as conn:
			row = conn.execute(
				"SELECT 1 FROM mission_events WHERE mission_id=? AND type=? AND ref=? AND summary=? LIMIT 1",
				(_clean_key(mission_id), str(event_type), str(ref), _clean_text(summary, _EVENT_SUMMARY_MAX)),
			).fetchone()
		return row is not None

	def count_events(
		self,
		mission_id: str,
		*,
		since_seq: int = 0,
		until_seq: Optional[int] = None,
		types: Optional[List[str]] = None,
		viewer_originator: Optional[str] = None,
		viewer_continuity_id: Optional[str] = None,
		include_hidden: bool = False,
	) -> int:
		"""Nº de eventos VISIBLES para `viewer_originator` desde `since_seq` (digest)."""
		mission = _clean_key(mission_id)
		if not mission:
			return 0
		params: list = [mission]
		sql = "SELECT COUNT(*) AS n FROM mission_events e LEFT JOIN note_status ns ON ns.event_id = e.event_id WHERE e.mission_id = ?"
		since = int(since_seq or 0)
		if since > 0:
			sql += " AND e.event_seq > ?"
			params.append(since)
		if until_seq is not None:
			sql += " AND e.event_seq <= ?"
			params.append(int(until_seq))
		sql += " AND (e.sealed = 0 OR ? = e.originator)"
		params.append(_clean_key(viewer_originator) if viewer_originator else "")
		sql += " AND (COALESCE(ns.status, 'visible') NOT IN ('hidden', 'retracted') OR ? = 1 OR e.continuity_id = ?)"
		params.extend([1 if include_hidden else 0, _clean_key(viewer_continuity_id) if viewer_continuity_id else ""])
		sql += " AND e.type NOT IN ('decision_opened', 'decision_upheld', 'decision_dismissed', 'decision_escalated', 'decision_moderated', 'decision_suggested')"
		# v8 (AD-095): la correspondencia no se renderiza en el tablón de la misión.
		viewer_soul = _clean_key(viewer_continuity_id) if viewer_continuity_id else ""
		sql += " AND (e.to_continuity IS NULL OR e.to_continuity = ? OR e.continuity_id = ?)"
		params.extend([viewer_soul, viewer_soul])
		if types:
			if not isinstance(types, (list, tuple)):
				raise ValueError("types debe ser una lista")
			known = [str(t) for t in types]
			unknown = [t for t in known if t not in EVENT_TYPES]
			if unknown:
				raise ValueError(f"tipos desconocidos: {unknown!r}")
			sql += " AND e.type IN (" + ",".join("?" * len(known)) + ")"
			params.extend(known)
		with self._connect() as conn:
			row = conn.execute(sql, tuple(params)).fetchone()
		return int(row["n"]) if row else 0

	# ── D23-SCORE: objeciones y decisiones dinámicas (D-obj) ────────────────
	def find_events_by_prefix(self, prefix: str, *, limit: int = 5) -> List[dict]:
		"""Eventos cuyo `event_id` empieza por `prefix` (para responder citando el id).

		El tablón renderiza un id corto legible; exigir los 32 hex para contestar es
		la diferencia entre un protocolo y un acertijo. La resolución exacta sigue
		mandando: quien llama decide si un prefijo es suficiente (y rechaza si es
		ambiguo). Mínimo 4 caracteres, para no resolver "a" contra todo.
		"""
		key = str(prefix or "").strip().lower()
		if len(key) < 4:
			return []
		with self._connect() as conn:
			rows = conn.execute(
				"SELECT * FROM mission_events WHERE event_id LIKE ? ORDER BY event_seq DESC LIMIT ?",
				(key + "%", max(1, min(int(limit), 20))),
			).fetchall()
		return [dict(r) for r in rows]

	def get_event(self, event_id: str) -> Optional[dict]:
		"""Evento por `event_id` (para validar el objetivo de una objeción)."""
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM mission_events WHERE event_id = ?", (str(event_id or ""),)).fetchone()
		if not row:
			return None
		event = dict(row)
		event["sealed"] = bool(event.get("sealed"))
		return event

	@staticmethod
	def _decision_dict(row: Any) -> dict:
		decision = dict(row)
		decision["requires_operator"] = bool(decision.get("requires_operator"))
		return decision

	def open_decision(
		self,
		*,
		subject_event_id: str,
		claim: str,
		created_by: str,
		mission_id: Optional[str] = None,
		evidence: str = "",
		severity: str = "low",
		proposed_action: str = "flag",
		ttl_h: float = 24.0,
	) -> dict:
		"""Abre una D-obj sobre una nota. Idempotente por (nota, objetor).

		`severity=high` o `proposed_action=retract` nacen `escalated`: solo el
		Operador puede resolverlas. El resto nace `open` con TTL para escalar.
		"""
		import uuid as _uuid

		subject = self.get_event(subject_event_id)
		if not subject:
			raise ValueError("la nota objetivo no existe")
		mission = _clean_key(mission_id or subject["mission_id"])
		if mission != subject["mission_id"]:
			raise ValueError("la objeción debe ser de la misma misión que la nota")
		creator = _clean_key(created_by)
		if not creator:
			raise ValueError("created_by requerido")
		text = _clean_text(claim, _EVENT_SUMMARY_MAX)
		if not text:
			raise ValueError("claim requerido")
		ev_text = _clean_text(evidence, _EVENT_SUMMARY_MAX) or None
		sev = str(severity or "low").strip().lower()
		if sev not in {"low", "medium", "high"}:
			raise ValueError(f"severity inválida: {severity!r}")
		action = str(proposed_action or "flag").strip().lower()
		if action not in {"flag", "hide", "retract"}:
			raise ValueError(f"proposed_action inválido: {proposed_action!r}")
		ttl = float(ttl_h)
		if ttl < 0:
			raise ValueError("ttl_h no puede ser negativo")

		requires_operator = sev == "high" or action == "retract"
		now = time.time()
		state = "escalated" if requires_operator else "open"
		expires_at = None if requires_operator else now + (ttl * 3600.0)
		decision_id = _uuid.uuid4().hex
		with self._connect() as conn:
			existing = conn.execute(
				"SELECT * FROM dynamic_decisions WHERE subject_event_id = ? AND created_by = ? ORDER BY created_at DESC LIMIT 1",
				(subject["event_id"], creator),
			).fetchone()
			if existing:
				result = self._decision_dict(existing)
				result["created"] = False
				return result
			conn.execute(
				"""
				INSERT INTO dynamic_decisions (
					decision_id, subject_event_id, mission_id, claim, evidence, severity,
					proposed_action, state, owner, created_by, created_at, expires_at,
					requires_operator
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(
					decision_id,
					subject["event_id"],
					mission,
					text,
					ev_text,
					sev,
					action,
					state,
					"operator" if requires_operator else None,
					creator,
					now,
					expires_at,
					1 if requires_operator else 0,
				),
			)
			conn.commit()
		try:
			self.add_event(
				event_type="decision_opened",
				mission_id=mission,
				summary=f"{decision_id[:8]} {state}: {text}",
				continuity_id=creator,
				ref=decision_id,
			)
			if requires_operator:
				self.add_event(
					event_type="decision_escalated",
					mission_id=mission,
					summary=f"{decision_id[:8]} alta severidad/retract: Operador",
					continuity_id=creator,
					ref=decision_id,
				)
		except Exception as e:  # la D-obj ya vive; el fallo de auditoría no la revierte
			logger.warning(f"[D-obj] audit event failed for {decision_id}: {e}")
		result = self.get_decision(decision_id) or {}
		result["created"] = True
		return result

	def get_decision(self, decision_id: str) -> Optional[dict]:
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM dynamic_decisions WHERE decision_id = ?", (str(decision_id or ""),)).fetchone()
		return self._decision_dict(row) if row else None

	def review_decision(
		self,
		decision_id: str,
		*,
		reviewer_continuity_id: str,
		action: str,
		reason: str = "",
		confidence: Optional[str] = None,
	) -> dict:
		"""Revisor independiente: uphold (flag), dismiss o escalate. Nunca hide.

		Si la D-obj tiene review job, solo el revisor asignado puede actuar y el
		modo manda: `review` usa `suggest_review`; `semi` exige `confidence=high`
		para mutar. El Operador resuelve escalated/high/retract con `moderate_note`.
		"""
		reviewer = _clean_key(reviewer_continuity_id)
		if not reviewer:
			raise ValueError("reviewer_continuity_id requerido")
		act = str(action or "").strip().lower()
		if act not in {"uphold", "dismiss", "escalate"}:
			raise ValueError(f"acción inválida: {action!r}")
		conf = str(confidence or "").strip().lower()
		if conf and conf not in {"low", "medium", "high"}:
			raise ValueError(f"confidence inválida: {confidence!r}")
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM dynamic_decisions WHERE decision_id = ?", (str(decision_id or ""),)).fetchone()
			if not row:
				raise ValueError("la decisión no existe")
			decision = dict(row)
			subject = conn.execute(
				"SELECT continuity_id FROM mission_events WHERE event_id = ?",
				(decision["subject_event_id"],),
			).fetchone()
			if reviewer == decision["created_by"]:
				raise ValueError("el objetor no puede revisar su propia objeción")
			if subject and reviewer == subject["continuity_id"]:
				raise ValueError("el autor de la nota no puede revisarla")
			review_row = conn.execute(
				"SELECT job_id, mode, reviewer_continuity_id FROM decision_reviews WHERE decision_id = ? ORDER BY created_at DESC LIMIT 1",
				(decision["decision_id"],),
			).fetchone()
			if review_row:
				if reviewer != _clean_key(review_row["reviewer_continuity_id"]):
					raise ValueError("el revisor asignado a esta D-obj es otro")
				mode = str(review_row["mode"])
				if mode == "review":
					raise ValueError("modo review: usa suggest_review")
				if not conf:
					raise ValueError("confidence obligatoria para un review job")
				if mode == "semi" and act != "escalate" and conf != "high":
					raise ValueError("modo semi: requiere confidence=high; usa escalate")
			if decision["state"] == "escalated":
				if act != "escalate":
					raise ValueError("decisión escalada: solo el Operador puede resolverla")
				if review_row and conf:
					conn.execute(
						"UPDATE decision_reviews SET confidence = ? WHERE job_id = ?",
						(conf, review_row["job_id"]),
					)
					conn.commit()
				return self._decision_dict(row)
			if decision["state"] != "open":
				raise ValueError(f"decisión ya cerrada: {decision['state']}")
			if bool(decision["requires_operator"]) and act != "escalate":
				raise ValueError("alta severidad/retract: solo el Operador puede resolverla")
			now = time.time()
			new_state = "escalated" if act == "escalate" else ("upheld" if act == "uphold" else "dismissed")
			owner = "operator" if act == "escalate" else reviewer
			conn.execute(
				"UPDATE dynamic_decisions SET state = ?, owner = ?, resolved_at = ?, resolution_reason = ? WHERE decision_id = ?",
				(new_state, owner, None if act == "escalate" else now, _clean_text(reason, _EVENT_SUMMARY_MAX) or None, decision["decision_id"]),
			)
			if review_row and conf:
				conn.execute(
					"UPDATE decision_reviews SET confidence = ? WHERE job_id = ?",
					(conf, review_row["job_id"]),
				)
			conn.commit()
		if act == "uphold":
			current = self.get_note_status(decision["subject_event_id"])
			if current not in {"hidden", "retracted"}:
				self._set_note_status(decision["subject_event_id"], decision["mission_id"], "flagged", reviewer, reason)
		event_type = {"uphold": "decision_upheld", "dismiss": "decision_dismissed", "escalate": "decision_escalated"}[act]
		try:
			self.add_event(
				event_type=event_type,
				mission_id=decision["mission_id"],
				summary=f"{decision['decision_id'][:8]} {act}: {reason or ''}",
				continuity_id=reviewer,
				ref=decision["decision_id"],
			)
		except Exception as e:
			logger.warning(f"[D-obj] audit event failed for {decision['decision_id']}: {e}")
		return self.get_decision(decision["decision_id"]) or {}

	def suggest_review(
		self,
		decision_id: str,
		*,
		reviewer_continuity_id: str,
		verdict: str,
		confidence: str,
		reason: str = "",
	) -> dict:
		"""Modo review: registra una sugerencia del revisor SIN mutar la D-obj.

		La decisión sigue siendo del Operador. Se guarda el último veredicto y su
		confianza; el reviewer no puede ser el autor de la nota ni el objetor.
		"""
		reviewer = _clean_key(reviewer_continuity_id)
		if not reviewer:
			raise ValueError("reviewer_continuity_id requerido")
		act = str(verdict or "").strip().lower()
		if act not in {"uphold", "dismiss", "escalate"}:
			raise ValueError(f"verdict inválido: {verdict!r}")
		conf = str(confidence or "").strip().lower()
		if conf not in {"low", "medium", "high"}:
			raise ValueError(f"confidence inválida: {confidence!r}")
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM dynamic_decisions WHERE decision_id = ?", (str(decision_id or ""),)).fetchone()
			if not row:
				raise ValueError("la decisión no existe")
			decision = dict(row)
			if decision["state"] in {"upheld", "dismissed"}:
				raise ValueError(f"decisión ya cerrada: {decision['state']}")
			subject = conn.execute(
				"SELECT continuity_id FROM mission_events WHERE event_id = ?",
				(decision["subject_event_id"],),
			).fetchone()
			if reviewer == decision["created_by"]:
				raise ValueError("el objetor no puede revisar su propia objeción")
			if subject and reviewer == subject["continuity_id"]:
				raise ValueError("el autor de la nota no puede revisarla")
			review_row = conn.execute(
				"SELECT mode, reviewer_continuity_id FROM decision_reviews WHERE decision_id = ? ORDER BY created_at DESC LIMIT 1",
				(decision["decision_id"],),
			).fetchone()
			if review_row:
				if reviewer != _clean_key(review_row["reviewer_continuity_id"]):
					raise ValueError("el revisor asignado a esta D-obj es otro")
				if str(review_row["mode"]) != "review":
					raise ValueError(f"modo {review_row['mode']}: usa review_decision")
			existing = conn.execute(
				"SELECT id, verdict, confidence, reason FROM decision_suggestions WHERE decision_id = ? AND reviewer_continuity_id = ?",
				(decision["decision_id"], reviewer),
			).fetchone()
			now = time.time()
			reason_clean = _clean_text(reason, _EVENT_SUMMARY_MAX) or None
			changed = True
			if existing:
				suggestion_id = int(existing["id"])
				changed = str(existing["verdict"]) != act or str(existing["confidence"]) != conf or (existing["reason"] or None) != reason_clean
				conn.execute(
					"UPDATE decision_suggestions SET verdict = ?, confidence = ?, reason = ?, created_at = ? WHERE id = ?",
					(act, conf, reason_clean, now, suggestion_id),
				)
			else:
				cur = conn.execute(
					"INSERT INTO decision_suggestions (decision_id, reviewer_continuity_id, verdict, confidence, reason, created_at) "
					"VALUES (?, ?, ?, ?, ?, ?)",
					(decision["decision_id"], reviewer, act, conf, reason_clean, now),
				)
				suggestion_id = int(cur.lastrowid or 0)
			conn.commit()
		if changed:
			try:
				self.add_event(
					event_type="decision_suggested",
					mission_id=decision["mission_id"],
					summary=f"{decision['decision_id'][:8]} suggest {act}/{conf}: {reason or ''}",
					continuity_id=reviewer,
					ref=decision["decision_id"],
				)
			except Exception as e:
				logger.warning(f"[D-obj] audit event failed for suggestion {decision['decision_id']}: {e}")
		return {
			"suggestion_id": suggestion_id,
			"decision_id": decision["decision_id"],
			"reviewer_continuity_id": reviewer,
			"verdict": act,
			"confidence": conf,
			"reason": reason_clean,
			"created_at": now,
		}

	def register_review_job(self, decision_id: str, *, job_id: str, reviewer_continuity_id: str, mode: str) -> None:
		"""Enlaza una D-obj con el job revisor que la está analizando."""
		with self._connect() as conn:
			conn.execute(
				"INSERT OR REPLACE INTO decision_reviews (job_id, decision_id, reviewer_continuity_id, mode, created_at) VALUES (?, ?, ?, ?, ?)",
				(
					str(job_id),
					str(decision_id),
					_clean_key(reviewer_continuity_id),
					str(mode),
					time.time(),
				),
			)
			conn.commit()

	def moderate_note(self, event_id: str, *, action: str, actor: str = "operator", reason: str = "") -> dict:
		"""Operador: flag/hide/retract/restore.

		`hide`/`retract` resuelven las D-obj open/escalated de la nota como
		`upheld`; `restore` como `dismissed`. `flag` solo marca la nota y deja la
		D-obj abierta (la resolverá el revisor o el TTL).
		"""
		act = str(action or "").strip().lower()
		status = {"flag": "flagged", "hide": "hidden", "retract": "retracted", "restore": "visible"}.get(act)
		if not status:
			raise ValueError(f"acción inválida: {action!r}")
		event = self.get_event(event_id)
		if not event:
			raise ValueError("la nota no existe")
		now = time.time()
		who = _clean_key(actor) or "operator"
		self._set_note_status(event_id, event["mission_id"], status, who, reason)
		resolved = 0
		if act in {"hide", "retract", "restore"}:
			new_state = "dismissed" if act == "restore" else "upheld"
			with self._connect() as conn:
				cur = conn.execute(
					"UPDATE dynamic_decisions SET state = ?, owner = ?, resolved_at = ?, resolution_reason = ? "
					"WHERE subject_event_id = ? AND state IN ('open', 'escalated')",
					(new_state, who, now, f"operator:{act}:{_clean_text(reason, _EVENT_SUMMARY_MAX)}", event_id),
				)
				conn.commit()
				resolved = int(cur.rowcount or 0)
		try:
			self.add_event(
				event_type="decision_moderated",
				mission_id=event["mission_id"],
				summary=f"{act} nota {event_id[:8]}: {reason or ''}",
				continuity_id=who,
				ref=event_id,
			)
		except Exception as e:
			logger.warning(f"[D-obj] audit event failed for moderate {event_id}: {e}")
		return {"event_id": event_id, "status": status, "action": act, "resolved_decisions": resolved}

	def get_note_status(self, event_id: str) -> str:
		with self._connect() as conn:
			row = conn.execute("SELECT status FROM note_status WHERE event_id = ?", (str(event_id or ""),)).fetchone()
		return str(row["status"]) if row else "visible"

	def get_note_statuses(self, event_ids: List[str]) -> dict:
		ids = [str(i) for i in event_ids if i]
		if not ids:
			return {}
		with self._connect() as conn:
			rows = conn.execute(
				"SELECT event_id, status FROM note_status WHERE event_id IN (" + ",".join("?" * len(ids)) + ")",
				tuple(ids),
			).fetchall()
		return {str(row["event_id"]): str(row["status"]) for row in rows}

	def _set_note_status(self, event_id: str, mission_id: str, status: str, actor: str, reason: str = "") -> None:
		with self._connect() as conn:
			conn.execute(
				"""
				INSERT INTO note_status (event_id, mission_id, status, updated_at, updated_by, reason)
				VALUES (?, ?, ?, ?, ?, ?)
				ON CONFLICT(event_id) DO UPDATE SET
					status = excluded.status,
					updated_at = excluded.updated_at,
					updated_by = excluded.updated_by,
					reason = excluded.reason
				""",
				(event_id, mission_id, status, time.time(), actor, _clean_text(reason, _EVENT_SUMMARY_MAX) or None),
			)
			conn.commit()

	def escalate_expired_decisions(self, now: Optional[float] = None) -> int:
		"""Sin revisor en TTL → escalated (Operador). Nunca oculta la nota."""
		now_ts = float(now if now is not None else time.time())
		with self._connect() as conn:
			rows = conn.execute(
				"SELECT decision_id, mission_id FROM dynamic_decisions WHERE state = 'open' AND expires_at IS NOT NULL AND expires_at < ?",
				(now_ts,),
			).fetchall()
			if not rows:
				return 0
			conn.executemany(
				"UPDATE dynamic_decisions SET state = 'escalated', owner = 'operator', resolution_reason = 'ttl' WHERE decision_id = ?",
				[(row["decision_id"],) for row in rows],
			)
			conn.commit()
		for row in rows:
			try:
				self.add_event(
					event_type="decision_escalated",
					mission_id=row["mission_id"],
					summary=f"{row['decision_id'][:8]} ttl: Operador",
					ref=row["decision_id"],
				)
			except Exception as e:
				logger.warning(f"[D-obj] audit event failed for ttl {row['decision_id']}: {e}")
		return len(rows)

	def list_decisions(
		self,
		*,
		mission_id: Optional[str] = None,
		states: Optional[List[str]] = None,
		limit: int = 100,
		pending_only: bool = True,
		escalate_expired: bool = True,
	) -> List[dict]:
		"""Bandeja de D-obj. Por defecto solo `open`/`escalated` (pendientes).

		La lista es lectura, pero con `escalate_expired=True` materializa el TTL
		perezoso (puede escribir `decision_escalated`). Filtra notas sealed y las
		ocultas/retiradas: no se re-expone su resumen por la bandeja.
		"""
		if escalate_expired:
			self.escalate_expired_decisions()
		mission = _clean_key(mission_id) if mission_id else None
		state_list = list(states) if states else (["open", "escalated"] if pending_only else [])
		params: list = []
		sql = (
			"SELECT d.*, e.summary AS note_summary, e.ref AS note_ref, e.type AS note_type, "
			"e.continuity_id AS note_author, e.created_at AS note_created_at, "
			"dr.job_id AS review_job_id, dr.mode AS review_mode, dr.reviewer_continuity_id AS reviewer, "
			"dr.confidence AS review_confidence, "
			"ds.verdict AS suggested_verdict, ds.confidence AS suggestion_confidence, "
			"ds.reason AS suggestion_reason, ds.created_at AS suggested_at "
			"FROM dynamic_decisions d LEFT JOIN mission_events e ON e.event_id = d.subject_event_id "
			"LEFT JOIN note_status ns ON ns.event_id = e.event_id "
			"LEFT JOIN (SELECT decision_id, job_id, mode, reviewer_continuity_id, confidence, created_at, "
			"ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY created_at DESC) AS rn "
			"FROM decision_reviews) dr ON dr.decision_id = d.decision_id AND dr.rn = 1 "
			"LEFT JOIN (SELECT decision_id, verdict, confidence, reason, created_at, "
			"ROW_NUMBER() OVER (PARTITION BY decision_id ORDER BY created_at DESC) AS rn "
			"FROM decision_suggestions) ds ON ds.decision_id = d.decision_id AND ds.rn = 1 "
			"WHERE COALESCE(e.sealed, 0) = 0 "
			"AND COALESCE(ns.status, 'visible') NOT IN ('hidden', 'retracted')"
		)
		if mission:
			sql += " AND d.mission_id = ?"
			params.append(mission)
		if state_list:
			sql += " AND d.state IN (" + ",".join("?" * len(state_list)) + ")"
			params.extend(state_list)
		sql += " ORDER BY d.requires_operator DESC, d.created_at ASC LIMIT ?"
		params.append(max(1, min(int(limit or 100), 500)))
		with self._connect() as conn:
			rows = conn.execute(sql, tuple(params)).fetchall()
		now = time.time()
		out: List[dict] = []
		for row in rows:
			item = self._decision_dict(row)
			item["age_s"] = max(0.0, now - float(item.get("created_at") or now))
			out.append(item)
		return out

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

	def expire_idle_legs(self, ttl_min: Optional[float] = None) -> int:
		"""Materializa el TTL de inactividad: legs sin latido → `expired`.

		El handshake vuelve a poner `active` el leg si reaparece (reactivación), y
		`purge_expired` (D14) lo borra 24 h después. Sin esto, `ttl_state` solo
		cambiaba con `unregister_session` y la retención nunca se disparaba.
		"""
		import red_pill.config as cfg

		minutes = float(ttl_min) if ttl_min is not None else float(getattr(cfg.get_config(), "MULTISESSION_IDLE_TTL_MIN", 30))
		cutoff = time.time() - max(0.0, minutes) * 60.0
		with self._connect() as conn:
			cur = conn.execute(
				"UPDATE session_registry SET ttl_state = 'expired', ttl_checked_at = ? WHERE ttl_state = 'active' AND updated_at < ?",
				(time.time(), cutoff),
			)
			conn.commit()
			return int(cur.rowcount or 0)

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
