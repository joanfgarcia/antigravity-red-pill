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
	def raw_enabled(self) -> bool:
		"""This subplugin's own on/off switch, independent of orchestration."""
		return getattr(cfg.get_config(), "MOOD_ANALYTICS_ENABLED", True)

	@property
	def is_enabled(self) -> bool:
		# Standalone in the main loop ONLY when the Mood Orchestrator is off; when
		# it is on, the orchestrator runs us directly (gating on raw_enabled), so
		# returning False here prevents double execution.
		return self.raw_enabled and not getattr(cfg.get_config(), "MOOD_ORCHESTRATOR_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		from red_pill.interceptors import _05_cognitive_router_state as _cr_state

		if _cr_state.is_casual_active():
			return ""

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

		import time

		now = time.time()
		threshold = getattr(cfg, "OVERNIGHT_THERAPY_THRESHOLD_HOURS", 4) * 3600

		session_points = []
		for p in points:
			p_time = float(p.payload.get("created_at", 0)) if p.payload else 0
			if now - p_time > threshold:
				break
			session_points.append(p)

		if not session_points:
			return ""

		colors = [p.payload.get("color", "gray") for p in session_points if p.payload and not p.payload.get("immune", False)]

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
