"""
Ferrari Plugin 09 — Proactive Signal
=======================================
Monitors for sustained critical emotional states and emits care signals.

Triggers:
	- RED sustained > PROACTIVE_SIGNAL_RED_THRESHOLD consecutive memories
		→ Injects care suggestion + writes pain signal to signal_memories (once per session)
	- High emotional volatility (> 3 color changes in last 5 memories)
		→ Injects stability note

Enable/Disable: PROACTIVE_SIGNAL_ENABLED=True in .env
Config: PROACTIVE_SIGNAL_RED_THRESHOLD (default: 5)
"""

import logging
from datetime import datetime

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin

logger = logging.getLogger(__name__)

_SAMPLE_SIZE = 10
_VOLATILITY_WINDOW = 5
_VOLATILITY_THRESHOLD = 3

# Module-level lock: track if we already emitted a pain signal this session
_pain_signal_emitted: bool = False


class ProactiveSignalPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Proactive Signal (Ferrari 09)"

	@property
	def timeout(self) -> float:
		return 1.5

	@property
	def raw_enabled(self) -> bool:
		"""This subplugin's own on/off switch, independent of orchestration."""
		return getattr(cfg.get_config(), "PROACTIVE_SIGNAL_ENABLED", True)

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

		global _pain_signal_emitted
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
			logger.warning(f"ProactiveSignalPlugin: scroll failed: {e}")
			return ""

		if not points:
			return ""

		colors = [p.payload.get("color", "gray") for p in points if p.payload and not p.payload.get("immune", False)]

		if not colors:
			return ""

		config = cfg.get_config()
		red_threshold = getattr(config, "PROACTIVE_SIGNAL_RED_THRESHOLD", 5)

		output_lines: list[str] = []

		# --- Check 1: Sustained RED state ---
		consecutive_red = 0
		for c in colors:
			if c == "red":
				consecutive_red += 1
			else:
				break

		if consecutive_red >= red_threshold:
			self.paint_chroma("red")
			output_lines += [
				"=== PROACTIVE SIGNAL (FERRARI PROTOCOL) ===",
				f"⚠️  ALERT: Operator has been in RED state for {consecutive_red} consecutive interactions.",
				"CARE_DIRECTIVE: Acknowledge emotional weight before any technical task.",
				"  → Consider suggesting a short break or checking on the Operator's wellbeing.",
				"  → Avoid pushing complex decisions or long work sessions.",
			]
			# Emit pain signal — once per session
			if not _pain_signal_emitted:
				try:
					from red_pill.memory import MemoryManager as _MM

					_m = _MM()
					_m.add_memory(
						collection="signal_memories",
						text=f"[FERRARI-09] Operator sustained RED state: {consecutive_red} consecutive interactions.",
						metadata={
							"title": "Ferrari 09: Sustained RED State",
							"details": f"{consecutive_red} consecutive RED interactions detected by Proactive Signal plugin.",
							"severity": 6.0,
							"source": "09_proactive_signal",
							"timestamp": datetime.now().isoformat(),
						},
						importance=6.0,
					)
					_pain_signal_emitted = True
					logger.warning("ProactiveSignalPlugin: sustained RED pain signal emitted.")
				except Exception as e:
					logger.error(f"ProactiveSignalPlugin: pain signal write failed: {e}")

		# --- Check 2: High volatility ---
		recent = colors[:_VOLATILITY_WINDOW]
		changes = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i - 1])
		if changes >= _VOLATILITY_THRESHOLD:
			if not output_lines:
				output_lines.append("=== PROACTIVE SIGNAL (FERRARI PROTOCOL) ===")
			output_lines += [
				f"⚡ NOTE: High emotional volatility detected ({changes} color shifts in last {len(recent)} memories).",
				"  → Operator may be processing complex emotions. Adapt pace accordingly.",
			]

		if output_lines:
			output_lines.append("---")
			return "\n".join(output_lines)
		return ""
