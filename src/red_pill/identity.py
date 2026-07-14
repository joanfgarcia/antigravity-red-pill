"""
Red Pill Identity Module

Handles the persistent but emergent baseline personality (Evolutionary Set Point).
"""

import json
import os
from typing import Any, Dict, cast

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


def get_hedonic_set_point() -> str:
	"""Returns the long-term dominant color (dynamic gravity point)."""
	identity = _load_identity()
	return str(identity.get("HEDONIC_SET_POINT_COLOR", getattr(cfg, "DEFAULT_COLOR", "gray")))


def get_default_emotion() -> str:
	"""Returns the default baseline emotion based on the gravity point."""
	identity = _load_identity()
	return str(identity.get("DEFAULT_EMOTION", getattr(cfg, "DEFAULT_EMOTION", "neutral")))


def update_identity(color: str, emotion: str) -> None:
	"""Updates the emergent personality baseline."""
	identity = _load_identity()
	identity["HEDONIC_SET_POINT_COLOR"] = color
	identity["DEFAULT_EMOTION"] = emotion
	_save_identity(identity)
