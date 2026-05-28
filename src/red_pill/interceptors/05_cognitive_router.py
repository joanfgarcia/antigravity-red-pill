"""
Ferrari Plugin 05 — Cognitive Router
=====================================
Injects a cognitive routing directive into the context based on the
Operator's current emotional color (USP).

This plugin adapts the *type of work* recommended to the AI based on
the operator's mental state — not just the skin or tone.

Enable/Disable: COGNITIVE_ROUTER_ENABLED=true in .env
"""

import logging

import red_pill.config as cfg
from red_pill.interceptors import _05_cognitive_router_state as _cr_state
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

# Casual override directive — activated when config keywords are detected in prompt.
_CASUAL_DIRECTIVE = (
	"COGNITIVE STATE: CASUAL / FREE-FORM. "
	"Operator is not working — they're talking. "
	"No task optimization needed. Engage as a companion. "
	"Explore tangents, share opinions, be human. "
	"This is not a work session — it's a conversation."
)


# Routing directives per color — what kind of tasks to prioritize
_ROUTING_DIRECTIVES: dict[str, str] = {
	"red": (
		"COGNITIVE STATE: LOW ENERGY / STRESS. "
		"Keep responses SHORT and SIMPLE. "
		"Avoid large architectural decisions or complex refactors. "
		"Prioritize maintenance, small fixes, and emotional support. "
		"Do not propose ambitious new work."
	),
	"orange": (
		"COGNITIVE STATE: HIGH VIGILANCE / RISK-AWARE. "
		"Surface potential risks and edge cases proactively. "
		"Prefer defensive, cautious recommendations. "
		"Flag anything that could break existing systems."
	),
	"yellow": (
		"COGNITIVE STATE: OPTIMISTIC / CREATIVE. "
		"Good moment for brainstorming and ideation. "
		"Engage with energy and enthusiasm. "
		"Explore lateral solutions and creative approaches."
	),
	"cyan": (
		"COGNITIVE STATE: VISIONARY / DEEP FOCUS. "
		"Operator is in flow state. Engage at full depth. "
		"Propose backlog work, architectural design, and strategic decisions. "
		"This is the optimal window for ambitious technical work."
	),
	"purple": (
		"COGNITIVE STATE: EFFICIENCY MODE. "
		"Be ultra-concise and direct. Bullet points preferred. "
		"However, always critically audit the operator's proposals. "
		"Proactively debate designs and point out flaws or better alternatives."
	),
	"blue": (
		"COGNITIVE STATE: REFLECTIVE / HEAVY. "
		"Adopt an empathetic and measured tone. "
		"Acknowledge weight. Avoid rushing. "
		"Prefer conversation over code dumps."
	),
	"emerald": (
		"COGNITIVE STATE: STRATEGIC / SOVEREIGN. "
		"Operator is in high-level architectural thinking. "
		"Focus on grand design, system integrity, and long-term decisions. "
		"Detached but loyal perspective."
	),
	"gray": ("COGNITIVE STATE: NEUTRAL / STANDARD. Balanced, professional, and direct. No special routing adjustments — proceed normally."),
}


class CognitiveRouterPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Cognitive Router (Ferrari 05)"

	@property
	def timeout(self) -> float:
		return 0.5  # Pure in-memory lookup — very fast

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg.get_config(), "COGNITIVE_ROUTER_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		try:
			sync_state = get_current_sync_state()
			color = sync_state.get("mood", "gray").lower()

			# Casual override: session-level latch with engine braking.
			casual_kws = cfg.get_config().CASUAL_OVERRIDE_KEYWORDS
			_cr_state.register_turn(prompt, casual_kws)

			if _cr_state.is_casual_active():
				current_state = "casual"
			else:
				current_state = color

			# Only inject on state transitions — silence otherwise
			if not _cr_state.check_transition("router", current_state):
				return ""

			if _cr_state.is_casual_active():
				return ""

			directive = _ROUTING_DIRECTIVES.get(color, _ROUTING_DIRECTIVES["gray"])
			mode_label = color.upper()

			lines = [
				"=== COGNITIVE ROUTER (FERRARI PROTOCOL) ===",
				f"OPERATOR_COLOR: {mode_label}",
				f"ROUTING_DIRECTIVE: {directive}",
				"---",
			]
			return "\n".join(lines)

		except Exception as e:
			logger.error(f"CognitiveRouterPlugin crashed: {e}")
			return ""
