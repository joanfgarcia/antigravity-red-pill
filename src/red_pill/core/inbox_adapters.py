"""Adaptadores de payload del inbox (neon-link `events.db` → worker).

Cada canal entrega su payload con su forma; el worker consume SIEMPRE el mismo
`InboxMessage`. Los adaptadores se registran por nombre de canal (plugin/IoC):
un canal/proveedor nuevo añade su lector sin tocar al worker.

Contrato del payload (neon-link): JSON con `text` (+ `sender_id`, `mode`,
`command` opcional). Los comandos pueden venir como clave directa (`command`) o
como un JSON embebido en `text` (protocolo heredado); el resto de textos NO son
JSON y no deben tratarse como error.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class InboxMessage:
	channel: str
	channel_user_id: str
	text: str = ""
	command: Optional[str] = None
	mode: str = "conversational"
	sender_id: Optional[str] = None
	payload: Dict[str, Any] = field(default_factory=dict)


Parser = Callable[[str, str, Dict[str, Any]], InboxMessage]

_ADAPTERS: Dict[str, Parser] = {}


def register_adapter(channel: str, parser: Parser) -> None:
	"""Registra el lector de payload de un canal (el último gana)."""
	_ADAPTERS[channel] = parser


def parse_payload(channel: str, channel_user_id: str, payload_raw: Any) -> InboxMessage:
	"""Payload crudo del inbox → `InboxMessage` normalizado (nunca lanza)."""
	try:
		payload = json.loads(payload_raw) if isinstance(payload_raw, (str, bytes)) else dict(payload_raw or {})
		if not isinstance(payload, dict):
			payload = {}
	except (json.JSONDecodeError, TypeError, ValueError):
		payload = {}
	parser = _ADAPTERS.get(channel, _generic)
	return parser(channel, channel_user_id, payload)


def _embedded_command(text: str) -> Optional[Dict[str, Any]]:
	"""JSON embebido en `text` (protocolo heredado de comandos) — solo si lo parece."""
	s = (text or "").strip()
	if not s.startswith("{"):
		return None
	try:
		nested = json.loads(s)
	except json.JSONDecodeError:
		return None
	return nested if isinstance(nested, dict) and "command" in nested else None


def _generic(channel: str, channel_user_id: str, payload: Dict[str, Any]) -> InboxMessage:
	text = str(payload.get("text", "") or "")
	command = payload.get("command")
	if command is None:
		nested = _embedded_command(text)
		if nested is not None:
			return InboxMessage(
				channel=channel,
				channel_user_id=channel_user_id,
				text=text,
				command=str(nested.get("command")),
				mode=str(nested.get("mode", payload.get("mode", "conversational"))),
				sender_id=payload.get("sender_id"),
				payload=nested,
			)
	return InboxMessage(
		channel=channel,
		channel_user_id=channel_user_id,
		text=text,
		command=str(command) if command else None,
		mode=str(payload.get("mode", "conversational")),
		sender_id=payload.get("sender_id"),
		payload=payload,
	)


register_adapter("telegram", _generic)
register_adapter("system", _generic)
