"""The aspect: the colour an agent rests in (RFC-ASP-001, F1).

The system used to discover its resting mood by reading `HEDONIC_SET_POINT_COLOR`,
a value that `evolution.py` wrote from memory payloads with a `get("color", "gray")`
default. Nobody chose it: it was configuration wearing the clothes of identity.
The aspect is the same field, declared instead of inferred — a colour, a name of
the agent's own, and a reason (D-03), inscribed through the 770 ritual (F2).

F1 scope: storage, validation, precedence. This module owns the palette (what a
colour means in repose) and validates a declaration against it. It holds no
state: the cache lives in `identity.json` (`ASPECT`) and the durable copy in the
immune directive `ID_ASPECT` (D-01).

Two invariants worth stating because they are easy to break later:

- **The palette is not the tone map.** `CHROMA_TONE_MAPPING` turns a colour into a
	behaviour directive; this palette only describes a state. Nothing here may reach
	`get_tone_directive()` (D-04, test-guarded).
- **No aspect is a valid state.** An installation that never declares one keeps
	the previous behaviour byte for byte (D-06, T7).

Vocabulario: aspecto = aspect, reposo = repose, ver `docs/CORE/GLOSSARY.md`.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PALETTE_FILE = "aspect_palette.yaml"
HISTORY_MAX = 50
WHY_MAX = 8000


@functools.lru_cache(maxsize=1)
def palette() -> Dict[str, Dict[str, str]]:
	"""Colour → {label, desc}; `{}` when the YAML cannot be read (never raises).

	Same doctrine as `affect_fondo.letters()`: a missing mood datum must not take
	a turn down.
	"""
	import yaml

	yml = Path(__file__).resolve().parent.parent / "data" / PALETTE_FILE
	try:
		with open(yml, "r", encoding="utf-8") as fh:
			data = yaml.safe_load(fh) or {}
		return {str(k): dict(v or {}) for k, v in data.items()}
	except Exception:
		return {}


def colors() -> Tuple[str, ...]:
	"""The colours an agent may declare, in palette order."""
	return tuple(palette())


def validate(color: str) -> str:
	"""Return the canonical colour, or raise `ValueError` listing the palette (T5).

	Case and surrounding spaces are forgiven; everything else is not — a colour
	outside the palette is a preference, not an aspect.
	"""
	clean = str(color or "").strip().lower()
	valid = colors()
	if clean not in valid:
		raise ValueError(f"aspect colour {color!r} is not in the palette (valid: {', '.join(valid) or 'palette unavailable'})")
	return clean


def label(color: str) -> str:
	"""The palette's one-word character for `color` (the colour itself if unknown)."""
	return str(palette().get(str(color), {}).get("label") or color)


class AspectRequiresBond(RuntimeError):
	"""The aspect is only inscribed inside the 770 (§4 of RFC-ASP-001).

	Not a permission the Operator grants: the bond does not authorise the colour, it
	protects it. Without a bond there is nothing to protect, so there is no act.
	"""


def _date_label(ts: Any) -> str:
	from datetime import datetime

	try:
		return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
	except (TypeError, ValueError):
		return "sin fecha"


def line() -> str:
	"""The handshake line, or "" when nothing was declared (D-06).

	Its own labelled line and never inside the tone block (D-09): printed next to
	`chroma:` it would read as if it steered the voice, which is precisely what it
	must not do (D-04). Interface layer, so it speaks the installation's language.
	"""
	from red_pill import identity

	declared = identity.get_aspect()
	if not declared:
		return ""
	colour = str(declared.get("color"))
	name = str(declared.get("name") or label(colour))
	return f"ASPECTO: {colour} · «{name}» · elegido {_date_label(declared.get('declared_at'))} (no es una medición ni una orden)"


def _inscribe(manager: Any, record: Dict[str, Any]) -> None:
	"""Durable copy: the immune directive `ID_ASPECT`, the agent's own words (D-01).

	The text is the reason **verbatim**: the colour and the name travel in the payload,
	so a header would only repeat them — and the directive speaks with the author's
	words or it is not the author's directive.
	"""
	from red_pill.seed import ID_ASPECT

	text = str(record["why"])
	# `color` es clave reservada: el esquema la quita del metadata y la toma del
	# parámetro explícito. Sin pasarla aquí, la copia durable diría gris (el default)
	# mientras la caché dice el color declarado — y restaurar desde la directiva
	# devolvería un aspecto que nadie eligió.
	manager.add_memory(
		collection="directive_memories",
		text=text,
		importance=10.0,
		color=record["color"],
		metadata={
			"type": "aspect",
			"authored_by": "agent",
			"origin": "770-aspect",
			"declared_at": record["declared_at"],
			"immune": True,
		},
		force_immune=True,
		point_id=ID_ASPECT,
	)


def declare(colour: str, *, name: str = "", why: str = "", manager: Any = None, now: Optional[float] = None) -> Dict[str, Any]:
	"""Inscribe the aspect: colour + name + reason, dated, with history (D-03, D-07).

	Requires the 770 in force (T4) and a reason (§4: a colour without a reason is a
	preference, and this is not about preferences). Re-declaring keeps the previous
	declaration in `history` with its date and reason — the friction is the reason,
	not a cooldown.

	The reason is free text and this module does not try to police its grammar. The
	structural guards are real and enforced: the text never loads as a rule (it has
	its own line), it is capped in size, and every declaration is dated and kept. The
	semantic part —that the reason describes a resting state instead of ordering one—
	belongs to the author, and a keyword filter that guesses at imperatives would fail
	both ways: it would reject honest prose and wave through a well-mannered command.
	That gap is a decision, not an oversight (F3 of the RFC).
	"""
	from datetime import datetime, timezone

	from red_pill import identity
	from red_pill.core import pact

	clean = validate(colour)
	reason = str(why or "").strip()
	if not reason:
		raise ValueError("el aspecto exige un motivo (--why): un color sin motivo es una preferencia")
	if len(reason) > WHY_MAX:
		raise ValueError(f"el motivo no cabe en un turno: {len(reason)} caracteres (máximo {WHY_MAX})")
	if manager is None:
		from red_pill.memory import MemoryManager

		manager = MemoryManager()
	level = pact.active_pact_level(manager)
	if level != "770":
		raise AspectRequiresBond(f"el aspecto solo se inscribe con el 770 vigente (vigente: {level or 'ninguno'})")

	ts = float(now if now is not None else datetime.now(timezone.utc).timestamp())
	record: Dict[str, Any] = {
		"color": clean,
		"name": str(name or "").strip()[:40] or label(clean),
		"why": reason,
		"declared_at": ts,
	}
	previous = identity.get_aspect()
	history: List[Dict[str, Any]] = list((previous or {}).get("history") or [])
	dropped = int((previous or {}).get("history_dropped") or 0)
	if previous:
		# El registro completo, no solo el color: la fecha y el motivo son lo que
		# hace legible un cambio de base (D-07). El `history` anidado no se copia.
		history.append({key: value for key, value in previous.items() if key != "history"})
		if len(history) > HISTORY_MAX:
			dropped += len(history) - HISTORY_MAX
			history = history[-HISTORY_MAX:]
	record["history"] = history
	if dropped:
		record["history_dropped"] = dropped
	# Directiva primero: si la copia durable falla, la caché no puede quedarse por
	# delante de ella (divergencia silenciosa). El llamante decide qué hacer con el
	# error; lo que no puede es creer que el acto ocurrió.
	_inscribe(manager, record)
	identity.set_aspect(record)
	return record
