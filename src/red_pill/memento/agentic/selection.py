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

NB-001 F5 (2026-11-10): el presupuesto por mensajes es un proxy, no el coste.
Con `MEMENTO_NIGHT_COST_MODEL_ENABLED` la selección presupuesta en la DIVISA de
cada fase, porque el coste real no es el mismo para las dos:

- `distill` es O(chars) → presupuesto en **chars** de work-unit.
- `annotate` es O(unidades)×2 + O(notas) → presupuesto en **unidades** y **notas
	esperadas** (predicción, no las notas reales — se expone para compararla con la
	duración real).

Ambas conservan el tope de sesiones y el anti-hambruna. Con el flag OFF (default)
la selección es byte-idéntica a la de siempre (msg_limit).

UNA sola implementación: la usan el `discover` del DAG
(`scripts/list_memento_agentic_pending.py`) y el pase clásico sin `--target`
(`scripts/memento_agentic.py`). Duplicarla fue cómo el tope por mensajes habría
quedado inerte en la mitad de las puertas de entrada.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def message_count(registry: Any, source: str, session_id: str) -> int:
	"""Tamaño de la sesión en mensajes (0 si no se puede leer)."""
	if registry is None:
		return 0
	try:
		entry = (registry.state.get("registry", {}).get(source, {}) or {}).get(session_id) or {}
		return int(entry.get("message_count") or 0)
	except Exception:
		return 0


def _entry(registry: Any, source: str, session_id: str) -> Dict[str, Any]:
	if registry is None:
		return {}
	try:
		return (registry.state.get("registry", {}).get(source, {}) or {}).get(session_id) or {}
	except Exception:
		return {}


def _work_units(root: Any, dir_rel: str) -> List[Any]:
	"""Los work units de una sesión (lista vacía si no se pueden leer)."""
	try:
		from .fragments import work_units

		return work_units(root / dir_rel)
	except Exception:
		return []


def work_unit_chars(root: Any, dir_rel: str) -> int:
	"""Suma de chars de los work units de una sesión (0 si no se puede leer)."""
	try:
		return sum(len(unit.content) for unit in _work_units(root, dir_rel))
	except Exception:
		return 0


def work_unit_count(root: Any, dir_rel: str) -> int:
	"""Número de work units (splits) de una sesión (0 si no se puede leer)."""
	try:
		return len(_work_units(root, dir_rel))
	except Exception:
		return 0


def predict_session_cost(
	root: Any,
	dir_rel: str,
	phase: Optional[str],
	*,
	notes_per_unit: Optional[int] = None,
) -> Dict[str, int]:
	"""Predicción de coste de una sesión en la divisa de su fase (NB-001 F5).

	- `distill`  → ``{"chars": N}`` (suma de chars de los work units).
	- `annotate` → ``{"units": N, "notes": M}`` (splits y notas esperadas).
	- `None`/otra fase → ``{}`` (sin predicción).

	Se expone para poder compararla con la duración real (P8.4): no decide qué
	ideas entran (el gate no se toca, D-NB-06), solo estima el coste de procesar
	la sesión en la fase dada.
	"""
	if root is None or not dir_rel:
		return {}
	if phase == "distill":
		return {"chars": work_unit_chars(root, dir_rel)}
	if phase == "annotate":
		units = work_unit_count(root, dir_rel)
		per_unit = notes_per_unit if notes_per_unit is not None else _annotate_notes_per_unit()
		return {"units": units, "notes": units * per_unit}
	return {}


def _cost_model_enabled() -> bool:
	"""Flag F5 (RULE 4): default OFF → presupuesto por mensajes, sin cambios."""
	try:
		import red_pill.config as cfg

		return bool(getattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", False))
	except Exception:
		return False


def _distill_char_limit() -> int:
	try:
		import red_pill.config as cfg

		return int(getattr(cfg, "MEMENTO_NIGHT_DISTILL_CHAR_LIMIT", 0))
	except Exception:
		return 0


def _annotate_unit_limit() -> int:
	try:
		import red_pill.config as cfg

		return int(getattr(cfg, "MEMENTO_NIGHT_ANNOTATE_UNIT_LIMIT", 0))
	except Exception:
		return 0


def _annotate_note_limit() -> int:
	try:
		import red_pill.config as cfg

		return int(getattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTE_LIMIT", 0))
	except Exception:
		return 0


def _annotate_notes_per_unit() -> int:
	try:
		import red_pill.config as cfg

		return int(getattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTES_PER_UNIT", 8))
	except Exception:
		return 8


def select_targets(
	pending: Sequence[Tuple[str, str, str]],
	limit: int,
	msg_limit: int = 0,
	registry: Optional[Any] = None,
	*,
	phase: Optional[str] = None,
	root: Optional[Any] = None,
) -> List[Tuple[str, str, str]]:
	"""Selección stale-first con topes de coste.

	`pending` es `[(source, session_id, reason)]` (la salida de `pending_agentic`).
	Devuelve el mismo trío, en el mismo orden, para que cada llamante elija su forma.

	Con `MEMENTO_NIGHT_COST_MODEL_ENABLED` OFF (default) el presupuesto variable es
	`msg_limit` (mensajes), igual que siempre. Con ON y una `phase` conocida, el
	presupuesto variable pasa a la divisa de la fase (chars para `distill`; unidades
	+ notas esperadas para `annotate`). En ambos casos se conserva el tope de
	sesiones y el anti-hambruna (la primera entra siempre).
	"""
	if limit <= 0:
		# `0` = sin tope: apaga AMBOS presupuestos (rescates manuales).
		return list(pending)
	ordered = sorted(pending, key=lambda t: t[2] != "stale")
	cost_model = _cost_model_enabled() and phase in ("distill", "annotate")
	chosen: List[Tuple[str, str, str]] = []
	total_msgs = 0
	total_chars = 0
	total_units = 0
	total_notes = 0
	for source, session_id, reason in ordered:
		if limit > 0 and len(chosen) >= limit:
			break
		if cost_model:
			dir_rel = _entry(registry, source, session_id).get("dir") or ""
			cost = predict_session_cost(root, dir_rel, phase)
			if phase == "distill":
				budget = _distill_char_limit()
				chars = cost.get("chars", 0)
				if budget > 0 and chosen and total_chars + chars > budget:
					break
				total_chars += chars
			else:  # annotate
				unit_budget = _annotate_unit_limit()
				note_budget = _annotate_note_limit()
				units = cost.get("units", 0)
				notes = cost.get("notes", 0)
				if unit_budget > 0 and chosen and total_units + units > unit_budget:
					break
				if note_budget > 0 and chosen and total_notes + notes > note_budget:
					break
				total_units += units
				total_notes += notes
		else:
			msgs = message_count(registry, source, session_id) if msg_limit > 0 else 0
			if msg_limit > 0 and chosen and total_msgs + msgs > msg_limit:
				break
			total_msgs += msgs
		chosen.append((source, session_id, reason))
	return chosen
