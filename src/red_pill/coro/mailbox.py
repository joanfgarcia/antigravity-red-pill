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


def _db():
	"""DB de neon-link con la ruta canónica de red-pill (nunca una copia)."""
	from neon_link import db as neon_db

	from red_pill.core.paths import get_neon_link_db_path

	path = str(get_neon_link_db_path())
	neon_db.set_db_path(path)
	if path not in _initialized_paths:
		neon_db.init_db()
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
			neon_db.init_db()
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
