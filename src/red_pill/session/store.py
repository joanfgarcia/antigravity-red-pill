"""`session.db` — reloj global de turnos + registro de sesiones (Alma y Coro).

Fase 0a: versión MÍNIMA pero con el esquema ratificado (ver DECISION_LOG).
El registro (`session_registry`) es el tablón: una fila por `originator`
(leg, `provider:session_id`), con su alma (`continuity_id`), misión, rol y linaje.
El reloj (`global_turn_seq`) da monotonicidad a los turnos (que `memory_queue.id`
no puede, por el dedup que devuelve ids existentes).

Fase 0b completará lo diferido (TTL materializado, git status espejo, claims y
eventos): aquí solo se declaran las columnas para no migrar dos veces.
"""

from __future__ import annotations

import json
import logging
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
"""


def _split_originator(originator: str) -> tuple[str, str]:
	"""`provider:session_id` → (provider, session_id). Sin `:` = (originator, '')."""
	provider, _, session_id = originator.partition(":")
	return (provider or originator), session_id


class SessionRegistry:
	"""Acceso a `session.db` (WAL + busy_timeout). Schema owned by Python."""

	def __init__(self, db_path: Optional[str] = None):
		self.db_path = str(db_path) if db_path else str(get_session_db())
		self._init_db()

	@contextmanager
	def _connect(self) -> Iterator[sqlite3.Connection]:
		conn = sqlite3.connect(self.db_path, timeout=30.0)
		try:
			conn.execute("PRAGMA journal_mode=WAL;")
			conn.execute("PRAGMA busy_timeout=5000;")
			conn.row_factory = sqlite3.Row
			yield conn
		finally:
			conn.close()

	def _init_db(self) -> None:
		from pathlib import Path

		Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
		with self._connect() as conn:
			conn.executescript(_SCHEMA)
			conn.commit()

	# ── Lecturas ────────────────────────────────────────────────────────────
	def get_by_originator(self, originator: str) -> Optional[dict]:
		with self._connect() as conn:
			row = conn.execute(
				"SELECT * FROM session_registry WHERE originator = ?", (originator,)
			).fetchone()
		return dict(row) if row else None

	def get_by_continuity(self, continuity_id: str) -> List[dict]:
		with self._connect() as conn:
			rows = conn.execute(
				"SELECT * FROM session_registry WHERE continuity_id = ? ORDER BY updated_at DESC",
				(continuity_id,),
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
	) -> None:
		"""UPSERT por `originator` (el leg). Política UNIFICADA "primer enlace gana por
		cuerpo" (F5): el `continuity_id` YA atado se conserva SIEMPRE — este es el
		único escritor con la invariante atómica (el hook del arnés usa la MISMA
		cláusula `ON CONFLICT ... SET continuity_id=session_registry.continuity_id`).
		`mission_id`/`updated_at`/afinidad sí se refrescan (el alma no se reescribe)."""
		provider, session_id = _split_originator(originator)
		affinity_json = json.dumps(canonize_affinity(affinity or []), ensure_ascii=False)
		now = time.time()
		with self._connect() as conn:
			conn.execute(
				"""
				INSERT INTO session_registry (
					originator, continuity_id, mission_id, campaign_id, role, lineage_id,
					provider, session_id, last_seen_global_turn, affinity_json, updated_at,
					branch, worktree, head_commit, title, intent
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(originator) DO UPDATE SET
					continuity_id = session_registry.continuity_id,
					mission_id = excluded.mission_id,
					campaign_id = excluded.campaign_id,
					role = excluded.role,
					lineage_id = excluded.lineage_id,
					provider = excluded.provider,
					session_id = excluded.session_id,
					last_seen_global_turn = excluded.last_seen_global_turn,
					affinity_json = excluded.affinity_json,
					updated_at = excluded.updated_at,
					branch = COALESCE(excluded.branch, session_registry.branch),
					worktree = COALESCE(excluded.worktree, session_registry.worktree),
					head_commit = COALESCE(excluded.head_commit, session_registry.head_commit),
					title = COALESCE(excluded.title, session_registry.title),
					intent = COALESCE(excluded.intent, session_registry.intent)
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
