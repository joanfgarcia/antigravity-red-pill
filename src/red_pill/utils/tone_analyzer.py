import logging
from typing import Dict

import red_pill.config as cfg
from red_pill.memory import MemoryManager

logger = logging.getLogger(__name__)


class ToneAnalyzer:
	"""
	B760 Tone Analysis Engine.
	Determines the dominant emotional chroma from recent memories.
	"""

	@staticmethod
	def get_dominant_mood(collection: str = "social_memories", limit: int = 3) -> str:
		"""
		Scrolls the latest memories to find the most frequent chroma.
		Increased limit for better sampling of the current context.
		"""
		try:
			from qdrant_client.http import models

			manager = MemoryManager()

			try:
				points, _ = manager.client.scroll(
					collection_name=collection,
					limit=limit,
					scroll_filter=models.Filter(must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))]),
					order_by=models.OrderBy(key="created_at", direction=models.Direction.DESC),
					with_payload=True,
					with_vectors=False,
				)
			except Exception as e:
				logger.debug(f"Scroll order_by failed, falling back to basic scroll: {e}")
				points, _ = manager.client.scroll(
					collection_name=collection,
					limit=limit,
					scroll_filter=models.Filter(must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))]),
					with_payload=True,
					with_vectors=False,
				)

			if not points:
				return cfg.DEFAULT_COLOR

			# High Reactivity Logic: Pick the first non-neutral emotion found in the latest memories
			# Otherwise, return the most frequent (consensus).
			latest_color = cfg.DEFAULT_COLOR
			for p in points:
				if p.payload and not p.payload.get("immune", False):
					color = p.payload.get("color", cfg.DEFAULT_COLOR)
					if color != cfg.DEFAULT_COLOR:
						return color
					if latest_color == cfg.DEFAULT_COLOR:
						latest_color = color

			return latest_color
		except Exception as e:
			logger.warning(f"Mood analysis failed: {e}")
			return cfg.DEFAULT_COLOR

	@staticmethod
	def get_tone_directive(mood_color: str) -> str:
		"""
		Retrieves the narrative refraction directive for a given color.
		"""
		return cfg.CHROMA_TONE_MAPPING.get(mood_color, cfg.CHROMA_TONE_MAPPING[cfg.DEFAULT_COLOR])


def get_current_sync_state() -> Dict[str, str]:
	"""
	Returns a dictionary with the dominant mood and its narrative directive.
	"""
	mood = ToneAnalyzer.get_dominant_mood()
	directive = ToneAnalyzer.get_tone_directive(mood)
	return {"mood": mood, "directive": directive}
