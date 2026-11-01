"""Avisos que despiertan al alma por el coro (S2.1+).

Qué resuelve
------------
Un job, un CI o un minion terminan cuando el agente ya no está mirando. Hasta
ahora el aviso iba por `soul_notify` (CLI/socket), que inyecta un turno pero no
deja carta en el tablón. Este helper publica un **mensaje `notify` dirigido al
alma** en `mission_events` y lo entrega por el canal `soul` (neon-link):

- el cuerpo queda en el tablón (durable, pull si el cuerpo está muerto);
- el `outbox` solo lleva el sobre;
- el `SoulHub` despierta al cuerpo vivo cuando corresponde;
- si el cuerpo está ocupado, el mensaje se queda `queued` y se entrega al abrir
  turno: **no interrumpe** el turno en curso.

La autoría es `job:<id>` (o el `originator` que se pase). `delivery._wake_verdict`
tiene una regla de cadena de mando: un aviso de job dirigido a su propia alma
puede despertarla aunque el cuerpo del job no tenga fila en el registro. Sin esa
regla, el aviso quedaría en pull y el job no despertaría a nadie.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from red_pill.coro import mailbox, protocol
from red_pill.session.store import SessionRegistry

logger = logging.getLogger(__name__)

_JOB_PREFIX = "job:"


def resolve_mission(continuity_id: str) -> str:
	"""Misión del alma según el registro (vacío si no hay fila)."""
	soul = str(continuity_id or "").strip()
	if not soul:
		return ""
	try:
		rows = SessionRegistry().get_by_continuity(soul)
	except Exception:
		return ""
	return str((rows[0] if rows else {}).get("mission_id") or "")


def _job_originator(originator: Optional[str]) -> str:
	value = str(originator or "").strip()
	if value.startswith(_JOB_PREFIX):
		return value
	return f"{_JOB_PREFIX}{value or 'unknown'}"


def publish_notice(
	*,
	continuity_id: str,
	body: str,
	originator: Optional[str] = None,
	mission_id: Optional[str] = None,
	thread_id: Optional[str] = None,
) -> bool:
	"""Publica un `notify` dirigido al alma y lo manda al outbox `soul`.

	Devuelve `True` si la carta quedó en el tablón y el sobre en el outbox.
	`False` si faltan datos o el buzón no está disponible; el llamante decide el
	fallback (`notify_soul`) o dejarlo para pull. Nunca lanza.
	"""
	soul = str(continuity_id or "").strip()
	text = str(body or "").strip()
	if not soul or not text:
		return False
	mission = str(mission_id or "").strip() or resolve_mission(soul)
	if not mission:
		logger.warning(f"[coro.notify] sin misión para {soul[:8]}; no se publica")
		return False
	author = _job_originator(originator)
	thread = str(thread_id or f"E-{uuid.uuid4().hex[:6]}")
	try:
		registry = SessionRegistry()
		event = registry.add_event(
			event_type="message",
			mission_id=mission,
			campaign_id=None,
			continuity_id=soul,
			originator=author,
			global_turn=registry.get_max_global_turn(),
			summary=text[:800],
			ref=None,
			sealed=False,
			to_continuity=soul,
			verb=protocol.VERB_NOTIFY,
			thread_id=thread,
			hop=0,
			hop_max=protocol.hop_max(),
			expects_reply=False,
			value_class=protocol.VALUE_NOW,
			expires_at=time.time() + protocol.budget_s(protocol.VERB_NOTIFY, protocol.VALUE_NOW),
		)
	except Exception as e:
		logger.warning(f"[coro.notify] no se pudo escribir el aviso para {soul[:8]}: {e}")
		return False
	return mailbox.publish_message(event)
