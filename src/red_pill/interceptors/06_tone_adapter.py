"""
Ferrari Plugin 06 — Tone Adapter
==================================
Signals the Operator's IMMEDIATE TONE: the dominant color of the current
session window (last 4h of memories, Overnight Therapy reset — see
OVERNIGHT_THERAPY_THRESHOLD_HOURS).

This is the fast signal of the pair: the Cognitive Router (05) reads the
3-day USP baseline instead. Separate from the Mystique skin — it tracks HOW
the AI should speak right now, not the persona it wears. Emits a compact
TONE_COLOR tag; the tone meaning per color is explained once by the Mood
Orchestrator's CHROMA KEY legend.

Enable/Disable: TONE_ADAPTER_ENABLED=true in .env
"""

import logging

import red_pill.config as cfg
from red_pill.interceptors import _05_cognitive_router_state as _cr_state
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)


class ToneAdapterPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Tone Adapter (Ferrari 06)"

	@property
	def timeout(self) -> float:
		return 0.5

	@property
	def raw_enabled(self) -> bool:
		"""This subplugin's own on/off switch, independent of orchestration."""
		return getattr(cfg.get_config(), "TONE_ADAPTER_ENABLED", True)

	@property
	def is_enabled(self) -> bool:
		# Standalone in the main loop ONLY when the Mood Orchestrator is off; when
		# it is on, the orchestrator runs us directly (gating on raw_enabled), so
		# returning False here prevents double execution.
		return self.raw_enabled and not getattr(cfg.get_config(), "MOOD_ORCHESTRATOR_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		try:
			sync_state = get_current_sync_state()
			color = sync_state.get("mood", "gray").lower()

			# Determine current state key
			if _cr_state.is_casual_active():
				current_state = "casual"
			else:
				current_state = color

			# Only inject on state transitions — silence otherwise
			if not _cr_state.check_transition("tone", current_state):
				return ""

			# Casual override: read session-level latch from cognitive router.
			if _cr_state.is_casual_active():
				return ""

			# Compact tag only — the tone meaning per color lives in the single
			# CHROMA KEY legend rendered by the Mood Orchestrator.
			self.paint_chroma(color)
			window_h = getattr(cfg.get_config(), "OVERNIGHT_THERAPY_THRESHOLD_HOURS", 4)
			lines = [
				"=== TONE ADAPTER (FERRARI PROTOCOL) ===",
				f"TONE_COLOR: {color.upper()} ({window_h}h session window)",
				"---",
			]
			return "\n".join(lines)

		except Exception as e:
			logger.error(f"ToneAdapterPlugin crashed: {e}")
			return ""
