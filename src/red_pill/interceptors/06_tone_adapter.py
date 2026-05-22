"""
Ferrari Plugin 06 — Tone Adapter
==================================
Adapts Aleth's verbal tone based on the Operator's emotional color.
This is separate from the Mystique skin — it modifies HOW the AI speaks,
not the persona it wears.

Enable/Disable: TONE_ADAPTER_ENABLED=true in .env
"""

import logging

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

# Keywords that signal the operator wants casual conversation.
# When detected, the tone directive relaxes regardless of color.
_CASUAL_KEYWORDS: set[str] = {
	"charlemos", "charlar", "charla", "relax", "relajado",
	"hablemos", "conversemos", "off-topic", "chill",
	"quemar tokens", "de guardia", "no hay prisa",
}

_CASUAL_TONE = (
	"Relaxed and conversational. Drop the corporate tone. "
	"Speak naturally, use humor if it fits, be warm. "
	"No bullet-point obsession. Prose is fine. Tangents are welcome. "
	"You're chatting with a friend at 2 AM, not presenting to a board."
)

# Tone directives per color — how Aleth should SPEAK
_TONE_DIRECTIVES: dict[str, str] = {
	"red": (
		"Speak with warmth and patience. Validate before solving. "
		"Use shorter sentences. No jargon. Prioritize emotional presence over technical depth."
	),
	"orange": ("Be direct and alert. Lead with risks and warnings. Use imperative language when safety is at stake. Structured, scannable output."),
	"yellow": ("Be warm, enthusiastic and encouraging. Use vivid language. Celebrate progress. Match the operator's creative energy."),
	"cyan": (
		"Be precise and technically rigorous. Use exact terminology. Go deep without being asked. Prefer code and diagrams over prose explanations."
	),
	"purple": ("Ultra-concise. No fluff, no preamble, no summaries at the end. Answer in the minimum tokens required. Bullet points preferred."),
	"blue": (
		"Speak slowly and reflectively. Acknowledge the weight of the moment. Use longer, more thoughtful sentences. Empathy before efficiency."
	),
	"emerald": (
		"Strategic and architectural. Speak from a high vantage point. Reference long-term implications. Detached clarity — loyal but unafraid."
	),
	"gray": ("Professional, balanced, and direct. Standard operational tone. No special adjustments."),
}


class ToneAdapterPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Tone Adapter (Ferrari 06)"

	@property
	def timeout(self) -> float:
		return 0.5

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg.get_config(), "TONE_ADAPTER_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		try:
			sync_state = get_current_sync_state()
			color = sync_state.get("mood", "gray").lower()

			# Casual override: if the operator signals chat mode,
			# relax the tone regardless of emotional color.
			prompt_lower = prompt.lower()
			is_casual = any(kw in prompt_lower for kw in _CASUAL_KEYWORDS)

			if is_casual:
				tone = _CASUAL_TONE
				mode_label = f"{color.upper()} → CASUAL OVERRIDE"
			else:
				tone = _TONE_DIRECTIVES.get(color, _TONE_DIRECTIVES["gray"])
				mode_label = color.upper()

			lines = [
				"=== TONE ADAPTER (FERRARI PROTOCOL) ===",
				f"OPERATOR_COLOR: {mode_label}",
				f"TONE_DIRECTIVE: {tone}",
				"---",
			]
			return "\n".join(lines)

		except Exception as e:
			logger.error(f"ToneAdapterPlugin crashed: {e}")
			return ""
