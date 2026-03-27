"""
Ferrari Plugin 07 — Mood Analytics
=====================================
Analyzes the last 15 social_memories to compute emotional trend data:
  - Dominant color across the session sample
  - Trend direction (improving / stable / deteriorating)
  - Persistence: consecutive count of the current color

Enable/Disable: MOOD_ANALYTICS_ENABLED=True in .env
"""

import logging
from collections import Counter

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin

logger = logging.getLogger(__name__)

_SAMPLE_SIZE = 15
_NEUTRAL_COLORS = {"gray"}

# Emotional "weight" — higher = more intense / more concerning
_COLOR_WEIGHT: dict[str, int] = {
	"red": 6,
	"orange": 5,
	"blue": 4,
	"yellow": 3,
	"cyan": 2,
	"emerald": 2,
	"purple": 1,
	"gray": 0,
}


def _trend_label(first_half_weight: float, second_half_weight: float) -> str:
	delta = second_half_weight - first_half_weight
	if delta > 1.0:
		return "deteriorating ⬇"
	if delta < -1.0:
		return "improving ⬆"
	return "stable ↔"


class MoodAnalyticsPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Mood Analytics (Ferrari 07)"

	@property
	def timeout(self) -> float:
		return 1.0

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg.get_config(), "MOOD_ANALYTICS_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		try:
			from red_pill.memory import MemoryManager

			mem = MemoryManager()
			points, _ = mem.client.scroll(
				collection_name="social_memories",
				limit=_SAMPLE_SIZE,
				with_payload=True,
				with_vectors=False,
			)
		except Exception as e:
			logger.warning(f"MoodAnalyticsPlugin: scroll failed: {e}")
			return ""

		if not points:
			return ""

		colors = [p.payload.get("color", "gray") for p in points if p.payload and not p.payload.get("immune", False)]

		if not colors:
			return ""

		# Dominant color
		counter = Counter(colors)
		dominant = counter.most_common(1)[0][0]
		current = colors[0]  # most recent

		# Persistence: consecutive count of current color from the top
		persistence = 0
		for c in colors:
			if c == current:
				persistence += 1
			else:
				break

		# Trend: compare avg weight of first vs second half
		mid = len(colors) // 2 or 1
		first_half_avg = sum(_COLOR_WEIGHT.get(c, 0) for c in colors[mid:]) / max(len(colors[mid:]), 1)
		second_half_avg = sum(_COLOR_WEIGHT.get(c, 0) for c in colors[:mid]) / max(len(colors[:mid]), 1)
		trend = _trend_label(first_half_avg, second_half_avg)

		lines = [
			"=== MOOD ANALYTICS (FERRARI PROTOCOL) ===",
			f"DOMINANT_COLOR: {dominant.upper()}",
			f"TREND: {trend} (last {len(colors)} memories)",
			f"PERSISTENCE: {persistence} consecutive {current.upper()}",
			"---",
		]
		return "\n".join(lines)
