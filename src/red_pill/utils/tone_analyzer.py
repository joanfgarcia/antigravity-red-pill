import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
	from red_pill.memory import MemoryManager

import red_pill.config as cfg
from red_pill.identity import get_hedonic_set_point

logger = logging.getLogger(__name__)

_TONE_COLLECTIONS: List[str] = ["social_memories", "work_memories"]


class ToneAnalyzer:
	"""
	B760 Tone Analysis Engine.
	Determines the dominant emotional chroma from recent memories.
	Queries both social_memories and work_memories, merges by created_at,
	and applies overnight-therapy threshold + high-reactivity logic.
	"""

	@staticmethod
	def _scroll_collection(
		client: Any,
		collection: str,
		limit: int,
		scroll_filter: Any,
	) -> list:
		"""Scroll a single collection, falling back if order_by is unsupported."""
		from qdrant_client.http import models as qm

		try:
			points, _ = client.scroll(
				collection_name=collection,
				limit=limit,
				scroll_filter=scroll_filter,
				order_by=qm.OrderBy(key="created_at", direction=qm.Direction.DESC),
				with_payload=True,
				with_vectors=False,
			)
			return points if points is not None else []
		except Exception as e:
			logger.debug(f"Scroll order_by failed for {collection}, falling back: {e}")
			try:
				points, _ = client.scroll(
					collection_name=collection,
					limit=limit,
					scroll_filter=scroll_filter,
					with_payload=True,
					with_vectors=False,
				)
				return points if points is not None else []
			except Exception as e2:
				logger.warning(f"Scroll fallback also failed for {collection}: {e2}")
				return []

	@staticmethod
	def get_dominant_mood(
		collection: str = "social_memories",
		limit: int = 5,
		manager: Optional["MemoryManager"] = None,
	) -> str:
		"""
		Scrolls the latest memories across both social_memories and work_memories,
		merges them by created_at descending, and picks the dominant chroma.

		Args:
			collection: Ignored — kept for backward compat. Always queries both.
			limit: Per-collection scroll limit (total candidates = 2 * limit).
			manager: Optional MemoryManager instance to reuse.
		"""
		from red_pill.memory import MemoryManager as _MemoryManager

		try:
			from qdrant_client.http import models

			_manager = manager if manager is not None else _MemoryManager()
			scroll_filter = models.Filter(must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))])

			# Merge from both collections
			all_points = []
			for coll in _TONE_COLLECTIONS:
				all_points.extend(ToneAnalyzer._scroll_collection(_manager.client, coll, limit, scroll_filter))

			if not all_points:
				return str(get_hedonic_set_point())

			# Sort by created_at descending (newest first)
			all_points.sort(
				key=lambda p: float((p.payload or {}).get("created_at", 0)),
				reverse=True,
			)

			now = time.time()
			threshold = getattr(cfg, "OVERNIGHT_THERAPY_THRESHOLD_HOURS", 4) * 3600

			# Overnight Therapy Reset: if the newest memory is older than threshold, reset
			newest_time = float((all_points[0].payload or {}).get("created_at", 0))
			if now - newest_time > threshold:
				logger.debug(
					f"ToneAnalyzer: newest memory is {(now - newest_time) / 3600:.1f}h old (threshold {threshold / 3600:.0f}h) → overnight reset"
				)
				return str(get_hedonic_set_point())

			# Keep only session-window memories
			session_points = [p for p in all_points if now - float((p.payload or {}).get("created_at", 0)) <= threshold]

			if not session_points:
				return str(get_hedonic_set_point())

			# High Reactivity: first non-gray color wins
			for p in session_points:
				payload = p.payload or {}
				if payload.get("immune", False):
					continue
				color = payload.get("color", cfg.DEFAULT_COLOR)
				if color and color != cfg.DEFAULT_COLOR:
					logger.debug(f"ToneAnalyzer: dominant color={color} from {p.id}")
					return str(color)

			# All gray — return gray
			return str(get_hedonic_set_point())

		except Exception as e:
			logger.warning(f"Mood analysis failed: {e}")
			return str(get_hedonic_set_point())

	@staticmethod
	def get_tone_directive(mood_color: str) -> str:
		"""
		Retrieves the narrative refraction directive for a given color.
		"""
		return cfg.CHROMA_TONE_MAPPING.get(mood_color, cfg.CHROMA_TONE_MAPPING[cfg.DEFAULT_COLOR])


def get_current_sync_state(manager: Optional["MemoryManager"] = None) -> Dict[str, str]:
	"""
	Returns a dictionary with the dominant mood and its narrative directive.

	Args:
		manager: Optional MemoryManager instance to reuse (PERF-001).
			Pass an existing instance to avoid creating a redundant connection.
	"""
	if not cfg.DYNAMIC_EMOTION_SYNC:
		return {"mood": cfg.DEFAULT_COLOR, "directive": cfg.CHROMA_TONE_MAPPING[cfg.DEFAULT_COLOR]}

	mood = ToneAnalyzer.get_dominant_mood(manager=manager)
	directive = ToneAnalyzer.get_tone_directive(mood)
	return {"mood": mood, "directive": directive}
