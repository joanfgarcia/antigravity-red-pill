"""Leases de trabajo y de misión (B-01L / RFC-INTEROP-003).

Una sola tabla `session_leases` cubre dos scopes:

- `work`: un turno/job concreto (`lease_key=request_id`).
- `mission`: el mando de una misión (`lease_key=mission:<mission_id>`).

El lease no sustituye al `pending_turn` ni al estado del espejo: dice si el
trabajo sigue vivo. El watchdog (fase posterior) decide abortar; esta capa solo
persiste y valida heartbeats/techos.
"""

from __future__ import annotations

import json
import time
from typing import Any, List, Optional

from red_pill.core.paths import get_session_db
from red_pill.session.store import connect_session_db

_SCOPES = frozenset({"work", "mission"})
_STATES = frozenset({"active", "stalled", "aborted", "completed"})


class LeaseError(RuntimeError):
	"""Lease inválido o en estado incompatible."""


class LeaseHeld(LeaseError):
	"""Otro cuerpo/alma mantiene el lease."""


def _now() -> float:
	return time.time()


class LeaseStore:
	"""CRUD de `session_leases` sobre `session.db` (schema v7)."""

	def __init__(self, db_path: Optional[str] = None):
		self.db_path = str(db_path) if db_path else str(get_session_db())
		from red_pill.session.store import SessionRegistry

		SessionRegistry(self.db_path)  # dueño del schema v7

	def _connect(self):
		return connect_session_db(self.db_path)

	@staticmethod
	def _validate(
		*,
		lease_key: str,
		scope: str,
		subject_id: str,
		continuity_id: str,
		idle_ttl_s: int,
		max_wall_s: int,
	) -> None:
		if not lease_key.strip():
			raise ValueError("lease_key requerido")
		if scope not in _SCOPES:
			raise ValueError(f"scope de lease desconocido: {scope!r}")
		if not subject_id.strip():
			raise ValueError("subject_id requerido")
		if not continuity_id.strip():
			raise ValueError("continuity_id requerido")
		if int(idle_ttl_s) <= 0 or int(max_wall_s) <= 0:
			raise ValueError("idle_ttl_s y max_wall_s deben ser positivos")

	@staticmethod
	def _row(row: Any) -> Optional[dict]:
		return dict(row) if row is not None else None

	@staticmethod
	def _check_owner(
		row: Any,
		*,
		continuity_id: Optional[str] = None,
		holder_originator: Optional[str] = None,
	) -> None:
		if continuity_id is not None and str(row["continuity_id"]) != str(continuity_id):
			raise LeaseHeld(f"lease de otra alma: {row['continuity_id']}")
		if holder_originator is not None and str(row["holder_originator"] or "") != str(holder_originator):
			raise LeaseHeld(f"lease de otro holder: {row['holder_originator'] or '-'}")

	def begin_lease(
		self,
		lease_key: str,
		*,
		scope: str,
		subject_id: str,
		continuity_id: str,
		mission_id: Optional[str] = None,
		holder_originator: str = "",
		owner_kind: str = "work",
		idle_ttl_s: int = 900,
		max_wall_s: int = 1800,
		metadata: Optional[dict] = None,
	) -> dict:
		"""Crea/renueva un lease; idempotente si el mismo dueño ya lo tiene.

		Si otro `continuity_id`/holder mantiene un lease activo, lanza
		`LeaseHeld`. Un lease vencido se reemplaza (el dueño anterior ya no late).
		"""
		key = str(lease_key or "").strip()
		scope = str(scope or "").strip().lower()
		subject = str(subject_id or "").strip()
		continuity = str(continuity_id or "").strip()
		self._validate(
			lease_key=key,
			scope=scope,
			subject_id=subject,
			continuity_id=continuity,
			idle_ttl_s=idle_ttl_s,
			max_wall_s=max_wall_s,
		)
		now = _now()
		meta = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))
		with self._connect() as conn:
			conn.execute("BEGIN IMMEDIATE")
			current = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
			if current is not None and str(current["state"]) == "active":
				expires = min(
					float(current["last_heartbeat_at"]) + int(current["idle_ttl_s"]),
					float(current["started_at"]) + int(current["max_wall_s"]),
				)
				if expires > now:
					same_owner = (
						str(current["continuity_id"]) == continuity
						and str(current["holder_originator"] or "") == str(holder_originator or "")
					)
					if not same_owner:
						conn.rollback()
						raise LeaseHeld(
							f"lease {key!r} activo de continuity={current['continuity_id']} "
							f"holder={current['holder_originator'] or '-'}"
						)
					conn.execute(
						"UPDATE session_leases SET last_heartbeat_at=?, extended_by='runner' WHERE lease_key=?",
						(now, key),
					)
					conn.commit()
					row = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
					out = self._row(row)
					if out is None:
						raise LeaseError("no se pudo leer el lease")
					return out
			conn.execute(
				"""
				INSERT INTO session_leases (
					lease_key, scope, subject_id, continuity_id, mission_id,
					holder_originator, owner_kind, state, started_at,
					last_heartbeat_at, idle_ttl_s, max_wall_s, extended_by,
					reason, metadata_json
				) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, NULL, NULL, ?)
				ON CONFLICT(lease_key) DO UPDATE SET
					scope=excluded.scope,
					subject_id=excluded.subject_id,
					continuity_id=excluded.continuity_id,
					mission_id=excluded.mission_id,
					holder_originator=excluded.holder_originator,
					owner_kind=excluded.owner_kind,
					state='active',
					started_at=excluded.started_at,
					last_heartbeat_at=excluded.last_heartbeat_at,
					idle_ttl_s=excluded.idle_ttl_s,
					max_wall_s=excluded.max_wall_s,
					extended_by=NULL,
					reason=NULL,
					metadata_json=excluded.metadata_json
				""",
				(
					key,
					scope,
					subject,
					continuity,
					mission_id,
					str(holder_originator or ""),
					str(owner_kind or "work"),
					now,
					now,
					int(idle_ttl_s),
					int(max_wall_s),
					meta,
				),
			)
			conn.commit()
			row = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
		if row is None:
			raise LeaseError("no se pudo escribir el lease")
		return dict(row)

	def begin_work_lease(self, request_id: str, **kwargs: Any) -> dict:
		return self.begin_lease(
			request_id,
			scope="work",
			subject_id=request_id,
			**kwargs,
		)

	def begin_mission_lease(self, mission_id: str, *, continuity_id: str, **kwargs: Any) -> dict:
		return self.begin_lease(
			f"mission:{mission_id}",
			scope="mission",
			subject_id=mission_id,
			mission_id=mission_id,
			continuity_id=continuity_id,
			**kwargs,
		)

	def get(self, lease_key: str) -> Optional[dict]:
		with self._connect() as conn:
			row = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (str(lease_key),)).fetchone()
		return self._row(row)

	def active_mission_lease(self, mission_id: str) -> Optional[dict]:
		with self._connect() as conn:
			row = conn.execute(
				"SELECT * FROM session_leases WHERE lease_key=? AND state='active'",
				(f"mission:{mission_id}",),
			).fetchone()
		return self._row(row)

	def leases_for_continuity(self, continuity_id: str, *, include_closed: bool = False) -> List[dict]:
		sql = "SELECT * FROM session_leases WHERE continuity_id=?"
		if not include_closed:
			sql += " AND state='active'"
		sql += " ORDER BY started_at DESC"
		with self._connect() as conn:
			rows = conn.execute(sql, (str(continuity_id),)).fetchall()
		return [dict(row) for row in rows]

	def heartbeat(
		self,
		lease_key: str,
		*,
		source: str = "runner",
		continuity_id: Optional[str] = None,
		holder_originator: Optional[str] = None,
	) -> dict:
		key = str(lease_key or "").strip()
		now = _now()
		with self._connect() as conn:
			conn.execute("BEGIN IMMEDIATE")
			row = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
			if row is None:
				conn.rollback()
				raise LeaseError(f"lease desconocido: {key!r}")
			self._check_owner(row, continuity_id=continuity_id, holder_originator=holder_originator)
			state = str(row["state"])
			if state != "active":
				conn.commit()
				return dict(row)
			max_wall = float(row["started_at"]) + int(row["max_wall_s"])
			if now > max_wall:
				conn.execute(
					"UPDATE session_leases SET state='stalled', reason='max_wall', last_heartbeat_at=? WHERE lease_key=?",
					(now, key),
				)
				conn.commit()
				out = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
				return dict(out)
			conn.execute(
				"UPDATE session_leases SET last_heartbeat_at=?, extended_by=? WHERE lease_key=?",
				(now, str(source or "runner"), key),
			)
			conn.commit()
			out = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
		return dict(out)

	def extend_lease(
		self,
		lease_key: str,
		*,
		seconds: int,
		reason: str,
		actor: str = "model",
		max_ceiling_s: Optional[int] = None,
		continuity_id: Optional[str] = None,
		holder_originator: Optional[str] = None,
	) -> dict:
		key = str(lease_key or "").strip()
		extra = int(seconds)
		if extra <= 0:
			raise ValueError("seconds debe ser positivo")
		if not str(reason or "").strip():
			raise ValueError("reason requerido para extender el lease")
		with self._connect() as conn:
			conn.execute("BEGIN IMMEDIATE")
			row = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
			if row is None:
				conn.rollback()
				raise LeaseError(f"lease desconocido: {key!r}")
			self._check_owner(row, continuity_id=continuity_id, holder_originator=holder_originator)
			if str(row["state"]) != "active":
				conn.commit()
				return dict(row)
			current = int(row["max_wall_s"])
			ceiling = int(max_ceiling_s) if max_ceiling_s is not None else current + extra
			new_max = min(current + extra, max(current, ceiling))
			conn.execute(
				"UPDATE session_leases SET max_wall_s=?, extended_by=?, reason=?, last_heartbeat_at=? WHERE lease_key=?",
				(new_max, str(actor or "model"), str(reason)[:500], _now(), key),
			)
			conn.commit()
			out = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
		return dict(out)

	def finish(
		self,
		lease_key: str,
		*,
		state: str = "completed",
		reason: Optional[str] = None,
		continuity_id: Optional[str] = None,
		holder_originator: Optional[str] = None,
	) -> dict:
		key = str(lease_key or "").strip()
		if state not in {"completed", "aborted", "stalled"}:
			raise ValueError(f"estado final desconocido: {state!r}")
		with self._connect() as conn:
			conn.execute("BEGIN IMMEDIATE")
			row = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
			if row is None:
				conn.rollback()
				raise LeaseError(f"lease desconocido: {key!r}")
			self._check_owner(row, continuity_id=continuity_id, holder_originator=holder_originator)
			current = str(row["state"])
			if current in {"completed", "aborted"}:
				conn.commit()
				if current != state:
					raise LeaseError(f"lease {key!r} ya está {current}")
				return dict(row)
			if state == "completed" and current == "stalled" and str(row["reason"] or "") == "max_wall":
				conn.rollback()
				raise LeaseError(f"lease {key!r} superó max_wall; no se puede completar")
			conn.execute(
				"UPDATE session_leases SET state=?, reason=?, extended_by='runner' WHERE lease_key=?",
				(str(state), str(reason)[:500] if reason else None, key),
			)
			conn.commit()
			out = conn.execute("SELECT * FROM session_leases WHERE lease_key=?", (key,)).fetchone()
		return dict(out)

	def sweep(self, *, now: Optional[float] = None, mark_stalled: bool = True) -> List[dict]:
		"""Lista leases vencidos; opcionalmente los marca `stalled`.

		No los borra ni aborta turnos: el watchdog/runner decide el cierre.
		"""
		stamp = _now() if now is None else float(now)
		expired: List[dict] = []
		with self._connect() as conn:
			rows = conn.execute("SELECT * FROM session_leases WHERE state='active'").fetchall()
			for row in rows:
				idle_deadline = float(row["last_heartbeat_at"]) + int(row["idle_ttl_s"])
				wall_deadline = float(row["started_at"]) + int(row["max_wall_s"])
				if stamp <= idle_deadline and stamp <= wall_deadline:
					continue
				reason = "max_wall" if stamp > wall_deadline else "idle_ttl"
				out = dict(row)
				out["expired_reason"] = reason
				expired.append(out)
				if mark_stalled:
					cur = conn.execute(
						"UPDATE session_leases SET state='stalled', reason=? "
						"WHERE lease_key=? AND state='active' AND last_heartbeat_at=?",
						(reason, row["lease_key"], float(row["last_heartbeat_at"])),
					)
					if cur.rowcount:
						out["state"] = "stalled"
						out["reason"] = reason
			if mark_stalled and expired:
				conn.commit()
		return expired
