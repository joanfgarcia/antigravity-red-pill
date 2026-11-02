"""Publica sobres del coro en el outbox de neon-link (canal `soul`, S2.1).

Qué hace y qué NO hace
----------------------
- **Sí**: escribe una fila en `outbox(channel='soul', channel_user_id=<continuity>,
	payload=<sobre>)` para que el broker de neon-link intente la entrega y sea el
	dueño del estado de transporte (PENDING/SENT/FAILED, backoff, DLQ, redrive).
- **No**: no guarda el texto del mensaje. El cuerpo vive en `mission_events`
	(append-only); el sobre solo lleva la referencia (`event_id`) y los metadatos
	necesarios para entregar. Si el buzón guardara el texto, habríamos construido
	el segundo tablón que AD-094 prohíbe.
- **No**: no entrega. La entrega la hace neon-link (`plugins/soul.py`) llamando
	al puerto local de red-pill. Aquí solo se publica.

Best-effort por diseño: si neon-link está caído o la DB no está accesible, se
registra y se devuelve `False`; el evento sigue en `mission_events` y el pull lo
recoge. Nunca se pierde un mensaje por un fallo del buzón.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CHANNEL = "soul"
ENVELOPE_VERSION = 1
_initialized_paths: set[str] = set()


def build_envelope(event: Dict[str, Any]) -> Dict[str, Any]:
	"""Sobre de red mínimo: referencia al evento, sin texto."""
	return {
		"v": ENVELOPE_VERSION,
		"event_id": str(event.get("event_id") or ""),
		"mission_id": event.get("mission_id"),
		"continuity_id": event.get("to_continuity"),
		"verb": event.get("verb"),
		"thread_id": event.get("thread_id"),
		"reply_to": event.get("ref"),
		"hop": event.get("hop"),
		"hop_max": event.get("hop_max"),
		"expects_reply": bool(event.get("expects_reply")),
		"value_class": event.get("value_class"),
		"expires_at": event.get("expires_at"),
	}


def _quiet_init(neon_db) -> None:
	"""`init_db` imprime un banner a stdout; el CLI --json no puede tragarlo."""
	with contextlib.redirect_stdout(io.StringIO()):
		neon_db.init_db()


def _db():
	"""DB de neon-link con la ruta canónica de red-pill (nunca una copia)."""
	from neon_link import db as neon_db

	from red_pill.core.paths import get_neon_link_db_path

	path = str(get_neon_link_db_path())
	neon_db.set_db_path(path)
	if path not in _initialized_paths:
		_quiet_init(neon_db)
		_initialized_paths.add(path)
	return neon_db


def _outbox_has_deliver_after(conn) -> bool:
	"""¿La DB de neon-link tiene ya la columna de entrega diferida (0.8+)?"""
	try:
		return any(str(row[1]) == "deliver_after" for row in conn.execute("PRAGMA table_info(outbox)"))
	except Exception:
		return False


def publish_message(event: Dict[str, Any], *, db_path: Optional[str] = None) -> bool:
	"""Publica un evento dirigido en el outbox `soul`. Idempotente por `event_id`.

	Devuelve `True` si la fila existe (nueva o ya estaba); `False` si no se pudo
	publicar (neon-link caído, DB bloqueada, evento sin destinatario). No lanza.
	"""
	if os.getenv("REDPILL_CORO_MAILBOX_DISABLE") == "1":
		# Kill switch para tests y despliegues que aún no tienen el canal `soul`.
		# Sin él, el fallback `_push` sigue siendo la entrega.
		return False
	if not isinstance(event, dict):
		return False
	event_id = str(event.get("event_id") or "").strip()
	soul = str(event.get("to_continuity") or "").strip()
	if not event_id or not soul:
		return False
	envelope = build_envelope(event)
	if not envelope.get("mission_id"):
		return False
	try:
		if db_path:
			from neon_link import db as neon_db

			neon_db.set_db_path(db_path)
			_quiet_init(neon_db)
			conn = neon_db.get_connection()
		else:
			conn = _db().get_connection()
		try:
			columns = ["message_id", "channel", "channel_user_id", "payload"]
			values: list = [event_id, CHANNEL, soul, json.dumps(envelope, ensure_ascii=False)]
			delay = event.get("deliver_after")
			if delay:
				# Entrega diferida (RFC-OBS-006 F2): el hueco existe desde neon-link
				# 0.8. Con 0.7.x la columna no está y el mensaje sale ya — se degrada
				# avisando, en vez de romper la publicación.
				if _outbox_has_deliver_after(conn):
					columns.append("deliver_after")
					values.append(float(delay))
				else:
					logger.warning("[coro.mailbox] neon-link sin `deliver_after`: el mensaje sale ya (actualiza neon-link)")
			conn.execute(
				f"INSERT OR IGNORE INTO outbox ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
				tuple(values),
			)
			conn.commit()
		finally:
			conn.close()
		return True
	except Exception as e:
		logger.warning(f"[coro.mailbox] no se pudo publicar {event_id[:12]}: {e}")
		return False


def reconcile(*, limit: int = 200, hours: float = 24.0, dry_run: bool = False, since_seq: Optional[int] = None) -> Dict[str, Any]:
	"""Reconcilia `mission_events -> outbox` con marca de agua (no reenvía historia).

	Primera pasada: fija la marca en el `event_seq` máximo actual y **no publica**
	nada (evita resucitar mensajes viejos o de pruebas). A partir de ahí publica
	los mensajes dirigidos posteriores a la marca que no tengan recibo. Es
	idempotente por `event_id` y, si una publicación falla, no avanza la marca
	pasada ella: el siguiente pase la reintenta.

	`since_seq` permite un backfill explícito (p.ej. 0). `hours` se conserva por
	compatibilidad con el CLI antiguo; la ventana real es la marca de agua.
	"""
	import time

	from red_pill.core.paths import get_session_db
	from red_pill.session import delivery as _delivery
	from red_pill.session.store import connect_session_db

	_delivery.ensure_schema(str(get_session_db()))
	out: Dict[str, Any] = {
		"scanned": 0,
		"published": 0,
		"failed": 0,
		"events": [],
		"hours": hours,
		"dry_run": bool(dry_run),
		"baseline": False,
		"last_seq": 0,
	}
	try:
		with connect_session_db(str(get_session_db())) as conn:
			conn.execute(
				"CREATE TABLE IF NOT EXISTS mailbox_reconcile_state ("
				"id TEXT PRIMARY KEY, last_seq INTEGER NOT NULL)"
			)
			row = conn.execute("SELECT last_seq FROM mailbox_reconcile_state WHERE id = 'outbox'").fetchone()
			last = int(row[0]) if row else None
			if last is None and since_seq is None:
				last = int((conn.execute("SELECT COALESCE(MAX(event_seq), 0) FROM mission_events").fetchone() or [0])[0])
				out["baseline"] = True
				out["last_seq"] = last
				if not dry_run:
					conn.execute(
						"INSERT INTO mailbox_reconcile_state (id, last_seq) VALUES ('outbox', ?)"
						" ON CONFLICT(id) DO UPDATE SET last_seq = excluded.last_seq",
						(last,),
					)
					conn.commit()
				return out
			if since_seq is not None:
				last = max(0, int(since_seq))
			elif last is None:
				last = 0
			out["last_seq"] = last
			sql = (
				"SELECT e.event_seq, e.event_id, e.mission_id, e.to_continuity, e.verb,"
				" e.thread_id, e.ref, e.hop, e.hop_max, e.expects_reply, e.value_class, e.expires_at"
				" FROM mission_events e"
				" LEFT JOIN message_receipts r ON r.event_id = e.event_id AND r.continuity_id = e.to_continuity"
				" WHERE e.event_seq > ?"
				" AND e.to_continuity IS NOT NULL"
				" AND e.verb IN ('notify', 'ask', 'reply')"
				" AND e.sealed = 0"
				" AND (e.expires_at IS NULL OR e.expires_at > ?)"
				" AND r.event_id IS NULL"
				" ORDER BY e.event_seq ASC LIMIT ?"
			)
			rows = [dict(r) for r in conn.execute(sql, (last, time.time(), max(1, min(int(limit or 200), 1000)))).fetchall()]
			out["scanned"] = len(rows)
			last_ok = last
			for ev in rows:
				out["events"].append({"event_id": ev.get("event_id"), "seq": ev.get("event_seq"), "to": ev.get("to_continuity"), "verb": ev.get("verb")})
				if dry_run:
					continue
				if publish_message(ev):
					out["published"] += 1
					last_ok = int(ev["event_seq"])
				else:
					out["failed"] += 1
					break
			out["last_seq"] = last_ok
			if not dry_run and last_ok > last:
				conn.execute(
					"INSERT INTO mailbox_reconcile_state (id, last_seq) VALUES ('outbox', ?)"
					" ON CONFLICT(id) DO UPDATE SET last_seq = excluded.last_seq",
					(last_ok,),
				)
				conn.commit()
	except Exception as e:
		logger.warning(f"[coro.mailbox] reconcile no pudo leer/publicar: {e}")
	return out
