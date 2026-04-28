"""
Composite Scoring for Emotional Pre-Heating.

Score = intensity * recency_factor * color_weight

- intensity: raw value from engram payload (0-10)
- recency_factor: exponential decay from created_at
- 0-12h: 1.0 (fresh)
- 12-24h: 0.8
- 24-48h: 0.5
- 48h+: 0.2
- color_weight: emotional relevance multiplier
- purple: 1.5 (deep connection, flow)
- blue: 1.3 (empathy, reflection)
- red: 1.2 (intensity, passion)
- cyan: 0.8 (technical focus - low emotional value)
- gray: 0.3 (unprocessed - low confidence)
"""

import time

COLOR_WEIGHTS = {
	"purple": 1.5,
	"blue": 1.3,
	"red": 1.2,
	"emerald": 0.9,
	"orange": 0.7,
	"cyan": 0.8,
	"gray": 0.3,
}

RECENCY_BRACKETS = [
	(12 * 3600, 1.0),  # 0-12h
	(24 * 3600, 0.8),  # 12-24h
	(48 * 3600, 0.5),  # 24-48h
]
RECENCY_FLOOR = 0.2  # 48h+


def recency_factor(created_at: float, now: float | None = None) -> float:
	"""Calculate exponential decay factor based on age of memory."""
	now = now or time.time()
	age = now - created_at
	for bracket_secs, factor in RECENCY_BRACKETS:
		if age <= bracket_secs:
			return factor
	return RECENCY_FLOOR


def composite_score(
	intensity: float,
	color: str,
	created_at: float,
	strategy: str = "composite",
) -> float:
	"""Calculate the emotional composite score."""
	if strategy == "intensity":
		return intensity

	rf = recency_factor(created_at)
	cw = COLOR_WEIGHTS.get(color.lower(), 0.5)
	return round(intensity * rf * cw, 2)


def extract_contextual_metadata(payload: dict) -> dict:
	"""
	Extracts themes, tone description, and operator state
	from existing engram fields. No LLM inference required.
	"""
	emotion = payload.get("emotion", "neutral")
	color = payload.get("color", "gray")
	markers = payload.get("linguistic_markers", [])

	# Theme extraction from linguistic markers + keyword scan
	themes = [m for m in markers if len(m) > 3][:5]

	# Tone mapping from emotion -> natural language
	TONE_MAP = {
		"joy": "warm, enthusiastic",
		"sadness": "quiet, reflective",
		"love": "intimate, tender",
		"fear": "vulnerable, searching",
		"anger": "intense, direct",
		"surprise": "curious, engaged",
		"neutral": "calm, steady",
	}
	tone = TONE_MAP.get(emotion.lower(), "present, engaged")

	# Operator state inference from color
	STATE_MAP = {
		"purple": "deep focus, philosophical",
		"blue": "contemplative, processing",
		"red": "passionate, urgent",
		"cyan": "visionary, building",
	}
	state = STATE_MAP.get(color.lower(), "neutral")

	return {"themes": themes, "tone": tone, "operator_state": state}
