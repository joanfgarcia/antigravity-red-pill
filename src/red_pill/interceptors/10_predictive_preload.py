"""
Ferrari Plugin 10 — Predictive Preload
=========================================
Preloads relevant context from work/social memories based on the
Operator's current emotional color — before it's explicitly requested.

Color → Collection mapping:
	cyan / emerald → work_memories  (deep focus, architectural work)
	purple         → work_memories  (efficiency, last tasks summary)
	blue / red     → social_memories (empathy, reflective context)
	others         → no preload

Enable/Disable: PREDICTIVE_PRELOAD_ENABLED=True in .env
"""

import logging

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.tone_analyzer import get_current_sync_state

logger = logging.getLogger(__name__)

_MAX_SNIPPET_CHARS = 200
_TOP_K = 3

# Which collection to query per color + the search query hint
_PRELOAD_MAP: dict[str, tuple[str, str, int]] = {
	# color → (collection, query, top_k)
	"cyan": ("work_memories", "active technical work architecture code", 3),
	"emerald": ("work_memories", "strategic architecture long-term design decision", 2),
	"purple": ("work_memories", "recent tasks completed summary progress", 2),
	"blue": ("social_memories", "reflection emotional processing connection", 2),
	"red": ("social_memories", "support care wellbeing operator feeling", 2),
}


class PredictivePreloadPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Predictive Preload (Ferrari 10)"

	@property
	def timeout(self) -> float:
		return 2.0

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg.get_config(), "PREDICTIVE_PRELOAD_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		try:
			sync_state = get_current_sync_state()
			color = sync_state.get("mood", "gray").lower()

			if color not in _PRELOAD_MAP:
				return ""  # No preload for neutral/orange/yellow states

			collection, query, top_k = _PRELOAD_MAP[color]

			from red_pill.memory import MemoryManager

			mem = MemoryManager()
			results = mem.search_and_reinforce(
				collection=collection,
				query=query,
				limit=top_k,
			)

			if not results:
				return ""

			snippets = []
			for r in results:
				payload = getattr(r, "payload", {}) or {}
				text = payload.get("text", "")
				if text:
					snippet = text[:_MAX_SNIPPET_CHARS].strip()
					if len(text) > _MAX_SNIPPET_CHARS:
						snippet += "…"
					snippets.append(snippet)

			if not snippets:
				return ""

			lines = [
				"=== PREDICTIVE PRELOAD (FERRARI PROTOCOL) ===",
				f"PRELOADED_FROM: {collection} (color={color.upper()})",
			]
			for i, s in enumerate(snippets, 1):
				lines.append(f"  [{i}] {s}")
			lines.append("---")
			return "\n".join(lines)

		except Exception as e:
			logger.error(f"PredictivePreloadPlugin crashed: {e}")
			return ""
