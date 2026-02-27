import json
import logging
from typing import Dict, List, Tuple

import red_pill.config as cfg

logger = logging.getLogger(__name__)


# AFFECT_MODEL: PIONEER (Original Red Pill 5.0)
_PIONEER_MODEL: Dict[str, Tuple[float, float]] = {
	"joy": (0.8, 0.7),
	"happiness": (0.8, 0.6),
	"love": (0.9, 0.5),
	"surprise": (0.3, 0.9),
	"neutral": (0.0, 0.0),
	"sadness": (-0.8, 0.2),
	"fear": (-0.6, 0.9),
	"anger": (-0.7, 0.9),
	"disgust": (-0.8, 0.4),
	"anxiety": (-0.5, 0.8),
	"envy": (-0.4, 0.6),
	"embarrassment": (-0.3, 0.5),
	"ennui": (-0.5, 0.1),
	"nostalgia": (0.2, 0.3),
	"confusion": (-0.1, 0.4),
	"shame": (-0.7, 0.3),
	"guilt": (-0.6, 0.4),
	"desire": (0.5, 0.7),
}

# AFFECT_MODEL: ACADEMIC (Warriner 2013 / NRC VAD Normalized)
# Values scaled to [-1, 1] for Valence and [0, 1] for Arousal
_ACADEMIC_MODEL: Dict[str, Tuple[float, float]] = {
	"joy": (0.81, 0.72),
	"happiness": (0.85, 0.55),
	"love": (0.92, 0.48),
	"surprise": (0.42, 0.82),
	"neutral": (0.00, 0.25),
	"sadness": (-0.48, 0.35),
	"fear": (-0.64, 0.73),
	"anger": (-0.62, 0.78),
	"disgust": (-0.71, 0.42),
	"anxiety": (-0.58, 0.67),
	"envy": (-0.52, 0.58),
	"embarrassment": (-0.45, 0.45),
	"ennui": (-0.41, 0.22),
	"nostalgia": (0.35, 0.32),
	"confusion": (-0.28, 0.48),
	"shame": (-0.68, 0.44),
	"guilt": (-0.55, 0.42),
	"desire": (0.68, 0.62),
}


def _build_affect_map() -> Dict[str, Tuple[float, float]]:
	"""Builds the active AFFECT_MAP based on configuration."""
	# 1. Select base model
	if cfg.AFFECT_MODEL == "ACADEMIC":
		base = _ACADEMIC_MODEL.copy()
	else:
		if cfg.AFFECT_MODEL != "PIONEER":
			logger.warning(f"Unknown AFFECT_MODEL '{cfg.AFFECT_MODEL}'. Falling back to PIONEER.")
		base = _PIONEER_MODEL.copy()

	# 2. Apply Custom Overrides
	try:
		overrides = json.loads(cfg.AFFECT_CUSTOM_OVERRIDES)
		for emotion, coords in overrides.items():
			if isinstance(coords, (list, tuple)) and len(coords) == 2:
				base[emotion.lower()] = (float(coords[0]), float(coords[1]))
				logger.debug(f"ACE-CAL: Overriding '{emotion}' with {coords}")
	except (json.JSONDecodeError, ValueError) as e:
		if cfg.AFFECT_CUSTOM_OVERRIDES != "{}":
			logger.error(f"ACE-CAL: Failed to parse AFFECT_CUSTOM_OVERRIDES: {e}")

	return base


AFFECT_MAP = _build_affect_map()


def get_affect_coordinates(emotions: List[str]) -> Tuple[float, float]:
	"""Compute average Valence and Arousal for a set of emotions."""
	if not emotions:
		return 0.0, 0.0

	v_sum = 0.0
	a_sum = 0.0
	count = 0

	for e in emotions:
		e_low = e.lower()
		if e_low in AFFECT_MAP:
			v, a = AFFECT_MAP[e_low]
			v_sum += v
			a_sum += a
			count += 1

	if count == 0:
		return 0.0, 0.0

	return v_sum / count, a_sum / count


def get_emotional_stability_multiplier(emotions: List[str], intensity: float = 1.0) -> float:
	"""
	Calculates a multiplier for memory stability based on affect.
	Higher value = Lower decay.
	"""
	valence, arousal = get_affect_coordinates(emotions)

	# Scale arousal by intensity (intensity is on [0, 10] scale, we normalize to 1.0)
	effective_arousal = min(arousal * (intensity / 5.0), 1.0)

	# Valence Modifier: Negative valence increases stability (survival)
	valence_stability = abs(valence) if valence < 0 else 0.5 * valence

	# Combine: Stability increases with arousal (70%) and valence extremity (30%)
	# This formula (weighted average) is the core ACE stability heuristic.
	stability = (0.7 * effective_arousal) + (0.3 * valence_stability)

	# Multiplier for the decay rate: result in [0.1, 1.0]
	# 0.1 means 10x slower decay (high stability)
	# 1.0 means normal decay
	return max(0.1, 1.0 - (stability * 0.9))
