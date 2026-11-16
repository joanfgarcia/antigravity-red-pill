"""
Red Pill Identity Module

The baseline that survives a session: what the agent is when nothing is happening.

Three sources, in this order (RFC-ASP-001):

1. **The declared aspect** (`ASPECT`): colour, name and reason chosen by the agent
	through the 770 ritual. It wins over everything else (T1).
2. **The emergent set point**: what the sleep cycle calculated from memories
	(`HEDONIC_SET_POINT_COLOR`; `EMERGENT_SET_POINT_COLOR` once an aspect exists).
	Diagnosis, not identity.
3. **The configured default**: `DEFAULT_COLOR`, what an installation has before anything
	happens. (The old `HEDONIC_SET_POINT_COLOR` config knob was never read by anyone and is
	gone: a knob nobody reads is a claim about behaviour that the code does not make.)

The split is not cosmetic. D-04 forbids the aspect from becoming a behaviour
directive, so consumers that turn a colour into conduct read `get_emergent_set_point()`,
while consumers that report who the agent is read `get_hedonic_set_point()` or
`get_aspect()`.
"""

import json
import os
from typing import Any, Dict, Optional, cast

from red_pill.config import get_config
from red_pill.core.paths import get_state_dir

cfg = get_config()


def _load_identity() -> Dict[str, Any]:
	identity_file = str(get_state_dir() / "identity.json")
	if os.path.exists(identity_file):
		try:
			with open(identity_file, "r") as f:
				return cast(Dict[str, Any], json.load(f))
		except Exception:
			return {}
	return {}


def _save_identity(identity: Dict[str, Any]) -> None:
	identity_file = str(get_state_dir() / "identity.json")
	os.makedirs(os.path.dirname(identity_file), exist_ok=True)
	with open(identity_file, "w") as f:
		json.dump(identity, f, indent=4)


def get_aspect() -> Optional[Dict[str, Any]]:
	"""The declared aspect, or `None` when the agent never declared one (D-06).

	`identity.json` holds the fast-path cache; the durable copy is the immune
	directive `ID_ASPECT` (D-01), so losing state loses the cache, not the act.
	A malformed entry degrades to `None` instead of raising: an absent aspect is a
	valid state, a broken turn is not.
	"""
	aspect = _load_identity().get("ASPECT")
	if not isinstance(aspect, dict) or not aspect.get("color"):
		return None
	return aspect


def set_aspect(record: Dict[str, Any]) -> None:
	"""Store the declared aspect in the fast-path cache (durable copy: `ID_ASPECT`)."""
	identity = _load_identity()
	identity["ASPECT"] = dict(record)
	_save_identity(identity)


def get_hedonic_set_point() -> str:
	"""The resting colour: the declared aspect wins over the calculated value (T1)."""
	aspect = get_aspect()
	if aspect:
		return str(aspect["color"])
	identity = _load_identity()
	return str(identity.get("HEDONIC_SET_POINT_COLOR", getattr(cfg, "DEFAULT_COLOR", "gray")))


def get_emergent_set_point() -> str:
	"""The calculated baseline — what the sleep cycle measured, never the declared aspect.

	This is the colour a consumer may turn into behaviour (D-04). Once an aspect is
	in force the calculated value is stored as `EMERGENT_SET_POINT_COLOR`; without
	one it stays in the legacy `HEDONIC_SET_POINT_COLOR`, so an installation that
	never declared anything reads exactly what it read before (T7).
	"""
	identity = _load_identity()
	return str(
		identity.get("EMERGENT_SET_POINT_COLOR")
		or identity.get("HEDONIC_SET_POINT_COLOR")
		or getattr(cfg, "DEFAULT_COLOR", "gray")
	)


def get_default_emotion() -> str:
	"""Returns the default baseline emotion based on the gravity point."""
	identity = _load_identity()
	return str(identity.get("DEFAULT_EMOTION", getattr(cfg, "DEFAULT_EMOTION", "neutral")))


def update_identity(color: str, emotion: str) -> None:
	"""Store the calculated baseline; with an aspect in force it is diagnosis (D-02).

	The sleep cycle does not overwrite a declaration. When `ASPECT` exists the
	calculated colour goes to `EMERGENT_SET_POINT_COLOR` and stays visible as
	evidence, while `HEDONIC_SET_POINT_COLOR` keeps whatever it had. Without an
	aspect the legacy write happens untouched (T7).
	"""
	identity = _load_identity()
	key = "EMERGENT_SET_POINT_COLOR" if get_aspect() else "HEDONIC_SET_POINT_COLOR"
	identity[key] = color
	identity["DEFAULT_EMOTION"] = emotion
	_save_identity(identity)
