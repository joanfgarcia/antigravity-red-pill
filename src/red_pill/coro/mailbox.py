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
			conn.execute(
				"INSERT OR IGNORE INTO outbox (message_id, channel, channel_user_id, payload)"
				" VALUES (?, ?, ?, ?)",
				(event_id, CHANNEL, soul, json.dumps(envelope, ensure_ascii=False)),
			)
			conn.commit()
		finally:
			conn.close()
		return True
	except Exception as e:
		logger.warning(f"[coro.mailbox] no se pudo publicar {event_id[:12]}: {e}")
		return False


def reconcile(*, limit: int = 200, hours: float = 24.0, dry_run: bool = False) -> Dict[str, Any]:
	"""Reconcilia `mission_events -> outbox` para mensajes que se quedaron sin sobre.

	Quién lo usa: el `SoulHub` de neon-link lo invoca periódicamente (y el Operador
	puede lanzarlo con `red-pill coro reconcile`). No reenvía historia: solo mira
	eventos de las últimas `hours` horas (0 = sin corte), dirigidos, con verbo de
	despertar, no expirados y **sin recibo** (`message_receipts`). La publicación es
	idempotente por `event_id` (`INSERT OR IGNORE`), así que repetir no duplica.

	Devuelve `{scanned, published, failed, events, hours}`. `dry_run` no escribe.
	"""
	import time

	from red_pill.core.paths import get_session_db
	from red_pill.session import delivery as _delivery
	from red_pill.session.store import connect_session_db

	# El reconciliador puede correr antes de que nadie haya entregado nada:
	# asegura `message_receipts` (y migra/retira `event_deliveries`).
	_delivery.ensure_schema(str(get_session_db()))
	out: Dict[str, Any] = {"scanned": 0, "published": 0, "failed": 0, "events": [], "hours": hours, "dry_run": bool(dry_run)}
	cutoff = (time.time() - float(hours) * 3600) if float(hours or 0) > 0 else 0.0
	sql = (
		"SELECT e.event_seq, e.event_id, e.mission_id, e.to_continuity, e.verb,"
		" e.thread_id, e.ref, e.hop, e.hop_max, e.expects_reply, e.value_class, e.expires_at"
		" FROM mission_events e"
		" LEFT JOIN message_receipts r ON r.event_id = e.event_id AND r.continuity_id = e.to_continuity"
		" WHERE e.to_continuity IS NOT NULL"
		" AND e.verb IN ('notify', 'ask', 'reply')"
		" AND e.sealed = 0"
		" AND (e.expires_at IS NULL OR e.expires_at > ?)"
		" AND e.created_at >= ?"
		" AND r.event_id IS NULL"
		" ORDER BY e.event_seq ASC LIMIT ?"
	)
	try:
		with connect_session_db(str(get_session_db())) as conn:
			rows = [dict(r) for r in conn.execute(sql, (time.time(), cutoff, max(1, min(int(limit or 200), 1000)))).fetchall()]
	except Exception as e:
		logger.warning(f"[coro.mailbox] reconcile no pudo leer mission_events: {e}")
		return out
	out["scanned"] = len(rows)
	for ev in rows:
		out["events"].append({"event_id": ev.get("event_id"), "seq": ev.get("event_seq"), "to": ev.get("to_continuity"), "verb": ev.get("verb")})
		if dry_run:
			continue
		if publish_message(ev):
			out["published"] += 1
		else:
			out["failed"] += 1
	return out
