"""
Ferrari Plugin 05 — Cognitive Router
=====================================
Signals the Operator's COGNITIVE BASELINE: the dominant USP color over the
3-day horizon (multi-session, recomputed during sleep, survives the night).

This is the slow signal of the pair: the Tone Adapter (06) reads the
immediate 4h session window instead. Emits a compact COGNITIVE_COLOR tag on
state changes and stays silent otherwise; the color's meaning is explained
once by the Mood Orchestrator's CHROMA KEY legend, not inline here.

Enable/Disable: COGNITIVE_ROUTER_ENABLED=true in .env
"""

import logging

import red_pill.config as cfg
from red_pill.interceptors import _05_cognitive_router_state as _cr_state
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.mood_profile import get_dominant_operator_mood

logger = logging.getLogger(__name__)


def _get_cognitive_color() -> str:
	"""Dominant USP color over the last_3d horizon (persisted engram read)."""
	from red_pill.memory import MemoryManager

	return get_dominant_operator_mood(MemoryManager()).lower()


class CognitiveRouterPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Cognitive Router (Ferrari 05)"

	@property
	def timeout(self) -> float:
		return 2.0  # Single-point Qdrant retrieve of the USP engram

	@property
	def raw_enabled(self) -> bool:
		"""This subplugin's own on/off switch, independent of orchestration."""
		return getattr(cfg.get_config(), "COGNITIVE_ROUTER_ENABLED", True)

	@property
	def is_enabled(self) -> bool:
		# Standalone in the main loop ONLY when the Mood Orchestrator is off; when
		# it is on, the orchestrator runs us directly (gating on raw_enabled), so
		# returning False here prevents double execution.
		return self.raw_enabled and not getattr(cfg.get_config(), "MOOD_ORCHESTRATOR_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		try:
			color = _get_cognitive_color()

			# Casual override: session-level latch with engine braking.
			# Both vocabularies are operator-customizable via .env.
			config = cfg.get_config()
			_cr_state.register_turn(prompt, config.CASUAL_OVERRIDE_KEYWORDS, config.WORK_MODE_KEYWORDS)

			if _cr_state.is_casual_active():
				current_state = "casual"
			else:
				current_state = color

			# Only inject on state transitions — silence otherwise
			if not _cr_state.check_transition("router", current_state):
				return ""

			if _cr_state.is_casual_active():
				return ""

			# Compact tag only — the color's meaning is rendered ONCE by the
			# Mood Orchestrator's CHROMA KEY legend at the end of the pipeline.
			self.paint_chroma(color)
			lines = [
				"=== COGNITIVE ROUTER (FERRARI PROTOCOL) ===",
				f"COGNITIVE_COLOR: {color.upper()} (3-day baseline)",
				"---",
			]
			return "\n".join(lines)

		except Exception as e:
			logger.error(f"CognitiveRouterPlugin crashed: {e}")
			return ""
