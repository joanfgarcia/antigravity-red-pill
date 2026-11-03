"""Selección con DOS presupuestos del pase agéntico nocturno (2026-11-03).

El coste del ciclo tiene dos sumandos y el tope solo medía uno: una sesión de 10
mensajes y otra de 1.500 contaban igual, aunque la segunda cuesta 45 min de LLM.
Ahora hay dos presupuestos y gana el que se cruce primero:

- `limit` (sesiones) acota el coste fijo (distill + annotate por sesión).
- `msg_limit` (mensajes) acota el coste variable (~2 s/msg medidos).

La primera sesión entra siempre: un ítem mayor que el presupuesto no puede
quedarse fuera para siempre (hambruna). `limit == 0` apaga AMBOS presupuestos
(rescates manuales): el comentario de config dice "0 = sin tope" y debe ser
verdad; apagar solo el de sesiones dejaba el de mensajes actuando en silencio.

UNA sola implementación: la usan el `discover` del DAG
(`scripts/list_memento_agentic_pending.py`) y el pase clásico sin `--target`
(`scripts/memento_agentic.py`). Duplicarla fue cómo el tope por mensajes habría
quedado inerte en la mitad de las puertas de entrada.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple


def message_count(registry: Any, source: str, session_id: str) -> int:
	"""Tamaño de la sesión en mensajes (0 si no se puede leer)."""
	if registry is None:
		return 0
	try:
		entry = (registry.state.get("registry", {}).get(source, {}) or {}).get(session_id) or {}
		return int(entry.get("message_count") or 0)
	except Exception:
		return 0


def select_targets(
	pending: Sequence[Tuple[str, str, str]],
	limit: int,
	msg_limit: int = 0,
	registry: Optional[Any] = None,
) -> List[Tuple[str, str, str]]:
	"""Selección stale-first con dos topes de coste.

	`pending` es `[(source, session_id, reason)]` (la salida de `pending_agentic`).
	Devuelve el mismo trío, en el mismo orden, para que cada llamante elija su forma.
	"""
	if limit <= 0:
		# `0` = sin tope: apaga AMBOS presupuestos (rescates manuales).
		return list(pending)
	ordered = sorted(pending, key=lambda t: t[2] != "stale")
	chosen: List[Tuple[str, str, str]] = []
	total_msgs = 0
	for source, session_id, reason in ordered:
		if limit > 0 and len(chosen) >= limit:
			break
		msgs = message_count(registry, source, session_id) if msg_limit > 0 else 0
		if msg_limit > 0 and chosen and total_msgs + msgs > msg_limit:
			break
		chosen.append((source, session_id, reason))
		total_msgs += msgs
	return chosen
