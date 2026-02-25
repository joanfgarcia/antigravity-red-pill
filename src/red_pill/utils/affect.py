from typing import Dict, List, Tuple

# Russell's Circumplex Model Mapping
# Format: (Valence [-1, 1], Arousal [0, 1])
AFFECT_MAP: Dict[str, Tuple[float, float]] = {
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

	Principles:
	1. High Arousal (intensity) creates 'Flashbulb' memories (high stability).
	2. Negative Valence (trauma/fear) persists longer for survival.
	3. Neutral/Low-arousal memories erode fastest.
	"""
	valence, arousal = get_affect_coordinates(emotions)

	# Scale arousal by intensity
	effective_arousal = min(arousal * (intensity / 5.0), 1.0)

	# Valence Modifier: Negative valence increases stability (survival)
	# abs(valence) if valence < 0, else 0.5 * valence
	valence_stability = abs(valence) if valence < 0 else 0.5 * valence

	# Combine: Stability increases with arousal and valence extremity
	stability = (0.7 * effective_arousal) + (0.3 * valence_stability)

	# Multiplier for the decay rate: result in [0.1, 1.0]
	# 0.1 means 10x slower decay (high stability)
	# 1.0 means normal decay
	return max(0.1, 1.0 - (stability * 0.9))
