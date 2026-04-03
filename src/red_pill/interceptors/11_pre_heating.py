import logging
import time
from typing import List

from qdrant_client import models
from red_pill import config
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.memory import MemoryManager
from red_pill.utils.pre_heating_scorer import composite_score, extract_contextual_metadata

logger = logging.getLogger(__name__)


class EmotionalPreHeatingPlugin(BaseInterceptorPlugin):
	"""
	Ferrari Plugin 11 - Emotional Pre-Heating (Oracle Protocol)
	Loads enriched emotional context on the FIRST interceptor invocation.
	"""

	_has_fired: bool = False

	@property
	def name(self) -> str:
		return "Emotional Pre-Heating (Oracle Protocol)"

	@property
	def timeout(self) -> float:
		return 4.0

	@property
	def is_enabled(self) -> bool:
		return getattr(config, "PRE_HEATING_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		if EmotionalPreHeatingPlugin._has_fired:
			return ""

		mgr = MemoryManager()
		client = mgr.client

		candidates = []
		now = time.time()

		quality_threshold = getattr(config, "PRE_HEATING_QUALITY_THRESHOLD", 5.0)
		scoring_strategy = getattr(config, "PRE_HEATING_SCORING_STRATEGY", "composite")
		injection_mode = getattr(config, "PRE_HEATING_INJECTION_MODE", "contextual")
		colors = getattr(config, "PRE_HEATING_HOT_COLORS", ["purple", "blue", "red"])

		try:
			# 1. Fetch TOP 5 from social_memories (high emotion colors)
			if client.collection_exists("social_memories"):
				social_results, _ = client.scroll(
					collection_name="social_memories",
					scroll_filter=models.Filter(must=[models.FieldCondition(key="color", match=models.MatchAny(any=colors))]),
					limit=5,
					with_payload=True,
				)
				candidates.extend(social_results)

			# 2. Fetch TOP 3 from interaction_memories (recent raw context, last 48h)
			if client.collection_exists("interaction_memories"):
				lookback = getattr(config, "PRE_HEATING_LOOKBACK_HOURS", 48)
				cutoff_time = now - (lookback * 3600)

				interaction_results, _ = client.scroll(
					collection_name="interaction_memories",
					scroll_filter=models.Filter(must=[models.FieldCondition(key="created_at", range=models.Range(gte=cutoff_time))]),
					limit=5,
					with_payload=True,
				)
				candidates.extend(interaction_results)

		except Exception as e:
			logger.error(f"Pre-heating query failed: {e}")
			return ""

		# Score and sort
		scored_fragments = []
		for point in candidates:
			if not point.payload:
				continue

			intensity = point.payload.get("intensity", 0.0)
			color = point.payload.get("color", "gray")
			created_at = point.payload.get("created_at", 0.0)

			score = composite_score(intensity, color, created_at, strategy=scoring_strategy)

			# Additional safety: ensure it has valid content
			content = point.payload.get("content", "").strip()
			if not content:
				continue

			# Filter by category if we only want social/mixed
			cat = point.payload.get("category", "")
			if cat == "work":
				continue

			scored_fragments.append({"score": score, "payload": point.payload, "timestamp": created_at})

		# Sort by score DESC
		scored_fragments.sort(key=lambda x: x["score"], reverse=True)

		# Take TOP N
		max_fragments = getattr(config, "PRE_HEATING_MAX_FRAGMENTS", 3)
		top_fragments = scored_fragments[:max_fragments]

		# Filter by quality threshold
		top_fragments = [f for f in top_fragments if f["score"] >= quality_threshold]

		if not top_fragments:
			# Graceful degradation - better cold than hallucinating
			EmotionalPreHeatingPlugin._has_fired = True
			return ""

		parts = []
		parts.append("=== EMOTIONAL PRE-HEATING (ORACLE PROTOCOL) ===")
		parts.append("SESSION_CONTINUITY: Your emotional thread with the Operator is injected below.")
		parts.append("Do not repeat these themes verbatim — let them inform your tone implicitly.")

		for idx, frag in enumerate(top_fragments, 1):
			score = frag["score"]
			color = frag["payload"].get("color", "gray")
			age_hours = round((now - frag["timestamp"]) / 3600, 1)

			parts.append(f"\n[MEMORY_{idx} — {color}, score={score}, {age_hours}h ago]")

			if injection_mode == "contextual":
				meta = extract_contextual_metadata(frag["payload"])
				parts.append(f"  Themes: {', '.join(meta['themes']) if meta['themes'] else 'unspecified'}")
				parts.append(f"  Tone: {meta['tone']}")
				parts.append(f"  Operator state: {meta['operator_state']}")
			else:
				raw_text = frag["payload"].get("content", "")
				max_chars = getattr(config, "PRE_HEATING_MAX_CHARS_PER_FRAGMENT", 200)
				if len(raw_text) > max_chars:
					raw_text = raw_text[:max_chars] + "..."
				parts.append(f"  Content: {repr(raw_text)}")

		parts.append(f"\nCALIBRATION: Quality threshold is {quality_threshold}. Material is reliable.")
		parts.append("---")

		# Mark as fired so it doesn't trigger on subsequent turns
		EmotionalPreHeatingPlugin._has_fired = True
		return "\n".join(parts)
