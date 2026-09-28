"""Directivas del Búnker: filtro de vigencia por `superseded`.

Una directiva puede quedar **reemplazada** por otra: se marca con el campo
`superseded` = id (o uuid) del engrama que la reemplaza. `read_core_directives`
solo inyecta las directivas **activas** (`superseded` ausente o null), de modo
que no se concatenen versiones contradictorias (p.ej. el pacto 760 superado por
el 770) sin borrar ningún engrama — la historia se conserva, solo deja de
cargarse.
"""

from __future__ import annotations

from typing import Any, Iterable, List

SUPERSEDED_KEY = "superseded"
# Ausente, None, "" o el string "null" == activa (default).
_INACTIVE_SENTINELS = (None, "", "null", "None")


def is_active(payload: dict | None) -> bool:
	"""True si la directiva debe cargarse (no ha sido reemplazada)."""
	value = (payload or {}).get(SUPERSEDED_KEY)
	return value in _INACTIVE_SENTINELS


def active_directive_contents(points: Iterable[Any]) -> List[str]:
	"""Contenidos de las directivas `immune` y NO reemplazadas (orden de entrada)."""
	out: List[str] = []
	for p in points:
		payload = getattr(p, "payload", None) or {}
		if payload.get("immune") and is_active(payload):
			out.append(payload.get("content", ""))
	return out


def mark_superseded(manager: Any, point_id: str, replaced_by: str) -> bool:
	"""Marca `point_id` como reemplazada por `replaced_by` (id del engrama nuevo).

	No borra nada: solo escribe el campo `superseded` en el payload.
	"""
	try:
		manager.client.set_payload(
			collection_name="directive_memories",
			payload={SUPERSEDED_KEY: str(replaced_by)},
			points=[point_id],
		)
		return True
	except Exception:
		return False
