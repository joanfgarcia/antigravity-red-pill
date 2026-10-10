"""Identidad de sesión — funciones puras (Alma y Coro, Fase 0a).

- `new_continuity_id`: emite un alma nueva (UUIDv7, ordenable por tiempo).
- `resolve_default_mission`: gramática `mission_id` (`<scope>:<id>`), con la
	cascada por defecto `param → repo:<rama> → mission:adhoc-<fecha>` (A2/F6).
- `decorate_with_session_tag`: añade el tag `<session …/>` que el handshake
	repite en cada respuesta (F5); el Stop hook lo lee del transcript para atar
	`originator ↔ continuity_id`.

Puro a propósito: sin I/O, sin estado — testeable sin tocar la BD.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import uuid

_SESSION_TAG_RE = re.compile(r"<session\b[^>]*/>")


def _sanitize_attr(value: object) -> str:
	"""Sanea un valor de atributo del tag: sin `<>"` ni espacios (romperían el
	grammar del tag y la idempotencia de `decorate_with_session_tag`). El alma es
	un UUID (seguro); misión/leg son informativos — la misión autoritativa vive en
	el registro, no en el tag."""
	clean = re.sub(r'[<>"\s]+', "_", str(value if value is not None else "")).strip("_")
	return clean or "unknown"


def new_continuity_id() -> str:
	"""Emite un alma nueva: UUIDv7 (RFC 9562), string canónico.

	UUIDv7 = 48 bits de timestamp ms + versión 7 + variante + 74 bits aleatorios.
	Ordenable por tiempo de emisión (útil para linajes/consultas por rango).
	Python 3.12 no trae `uuid.uuid7()` (llega en 3.14), así que se construye aquí.
	"""
	ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000) & ((1 << 48) - 1)
	b = bytearray(os.urandom(16))
	b[0:6] = ms.to_bytes(6, "big")
	b[6] = (b[6] & 0x0F) | 0x70  # versión 7
	b[8] = (b[8] & 0x3F) | 0x80  # variante RFC 4122
	return str(uuid.UUID(bytes=bytes(b)))


def resolve_default_mission(
	mission_id: object = None,
	*,
	branch: str | None = None,
	today: _dt.date | None = None,
) -> str:
	"""Resuelve el `mission_id` efectivo (nunca vacío, A2).

	Cascada: `mission_id` explícito (canonizado) → `repo:<rama>` si hay rama
	(primera escritura desde un repo) → `mission:adhoc-<fecha>` (sin repo).
	El valor explícito se respeta verbatim (solo trim); legacy sin scope sigue
	válido. La gramática es `<scope>:<id>` (scopes: telegram, dossier, repo,
	adhoc, mission).
	"""
	if mission_id is not None:
		text = str(mission_id).strip()
		if text:
			return text
	if branch:
		clean = str(branch).strip()
		if clean:
			return f"repo:{clean}"
	d = today or _dt.date.today()
	return f"mission:adhoc-{d.isoformat()}"


def _parse_session_tags(text: str) -> list[dict]:
	"""Extrae los atributos de todos los `<session …/>` de un texto (para el hook
	y para los tests). Devuelve dicts con las claves presentes."""
	tags: list[dict] = []
	for raw in _SESSION_TAG_RE.findall(text):
		body = raw[len("<session") : -2]
		attrs: dict = {}
		for key, _eq, val in re.findall(r"(\w+)\s*=\s*(\"?)([^\"\s<>]+)\2", body):
			attrs[key] = val
		tags.append(attrs)
	return tags


def render_session_tag(*, continuity_id: str, originator: str | None = None, mission_id: str | None = None) -> str:
	"""Renderiza el tag `<session …/>` (F5). `leg` = originator compuesto.

	Se mantiene compacto y en una sola línea: el handshake lo repite en cada
	respuesta y el Stop hook lo localiza por regex.
	"""
	parts = [f'continuity_id="{_sanitize_attr(continuity_id)}"']
	parts.append(f'leg="{_sanitize_attr(originator) if originator else "unknown"}"')
	parts.append(f'mission="{_sanitize_attr(mission_id) if mission_id else "unknown"}"')
	return "<session " + " ".join(parts) + "/>"


def decorate_with_session_tag(
	text: str,
	*,
	continuity_id: str,
	originator: str | None = None,
	mission_id: str | None = None,
) -> str:
	"""Añade el tag `<session …/>` al final de `text` (idempotente por turno: se
	elimina cualquier tag previo para no acumular tags obsoletos)."""
	cleaned = _SESSION_TAG_RE.sub("", text).rstrip()
	tag = render_session_tag(continuity_id=continuity_id, originator=originator, mission_id=mission_id)
	return f"{cleaned}\n\n{tag}" if cleaned else tag
