"""
Ferrari Plugin 08 — Emotive Recall
======================================
Searches social_memories for past interactions where the Operator was
in the same emotional state as now. Injects emotional echoes — context
on how the Operator behaved and what they needed in a similar state.

Enable/Disable: EMOTIVE_RECALL_ENABLED=True in .env
"""

import logging
from typing import List

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

_MAX_ECHO_CHARS = 180  # Max chars per echo snippet
_TOP_K = 2


class EmotiveRecallPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Emotive Recall (Ferrari 08)"

	@property
	def timeout(self) -> float:
		return 2.0

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg.get_config(), "EMOTIVE_RECALL_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		from red_pill.interceptors import _05_cognitive_router_state as _cr_state

		if _cr_state.is_casual_active():
			return ""

		try:
			sync_state = get_current_sync_state()
			color = sync_state.get("mood", "gray")

			if color == "gray":
				return ""  # Neutral state — no emotional echo needed

			from red_pill.memory import MemoryManager

			mem = MemoryManager()

			# Semantic search for emotionally-similar past interactions
			query = f"operator {color} emotional state feeling interaction"
			results = mem.search_and_reinforce(
				collection="social_memories",
				query=query,
				limit=_TOP_K + 2,  # Extra to allow filtering
			)

			if not results:
				return ""

			# Filter by same color if payload has it, otherwise accept all
			echoes: List[str] = []
			for r in results:
				payload = getattr(r, "payload", {}) or {}
				# Prefer memories of matching color, but don't exclude others
				r_color = payload.get("color", color)
				if r_color == color or len(echoes) < _TOP_K:
					text = payload.get("content", "")
					if text:
						snippet = text[:_MAX_ECHO_CHARS].strip()
						if len(text) > _MAX_ECHO_CHARS:
							snippet += "…"
						echoes.append(snippet)
				if len(echoes) >= _TOP_K:
					break

			if not echoes:
				return ""

			lines = [
				"=== EMOTIVE RECALL (FERRARI PROTOCOL) ===",
				f"EMOTIONAL_ECHO ({color.upper()} state — past resonances):",
			]
			for i, echo in enumerate(echoes, 1):
				lines.append(f"  [{i}] {echo}")
			lines.append("---")
			return "\n".join(lines)

		except Exception as e:
			logger.error(f"EmotiveRecallPlugin crashed: {e}")
			return ""
