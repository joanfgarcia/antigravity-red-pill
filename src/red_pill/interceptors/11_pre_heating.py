import logging
import time

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
			# 1. Fetch wider pool from social_memories (HIPOCAMPO + AMÍGDALA)
			if client.collection_exists("social_memories"):
				social_results, _ = client.scroll(
					collection_name="social_memories",
					limit=100,
					with_payload=True,
				)

				# Filter valid payloads
				valid_social = [p for p in social_results if p.payload and p.payload.get("content", "").strip()]
				valid_social = [p for p in valid_social if p.payload.get("category", "") != "work"]

				# Sort by timestamp DESC (most recent first)
				valid_social.sort(key=lambda x: float(x.payload.get("created_at", 0)), reverse=True)

				# --- HIPPOCAMPUS (Continuity): Top 2 most recent regardless of color ---
				hippocampus = valid_social[:2]
				candidates.extend(hippocampus)

				# --- AMYGDALA (Emotional Anchors): Top 3 most intense with hot colors ---
				hippo_ids = {p.id for p in hippocampus}
				potential_amygdala = [p for p in valid_social if p.id not in hippo_ids]
				potential_amygdala = [p for p in potential_amygdala if p.payload.get("color", "gray") in colors]

				# Score Amygdala candidates
				for p in potential_amygdala:
					intensity = float(p.payload.get("intensity", 0.0))
					color = p.payload.get("color", "gray")
					created_at = float(p.payload.get("created_at", 0.0))
					p._temp_score = composite_score(intensity, color, created_at, strategy=scoring_strategy)

				# Filter by quality threshold and sort by highest score
				potential_amygdala = [p for p in potential_amygdala if getattr(p, "_temp_score", 0) >= quality_threshold]
				potential_amygdala.sort(key=lambda x: getattr(x, "_temp_score", 0), reverse=True)

				amygdala = potential_amygdala[:3]
				candidates.extend(amygdala)

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

		# Score and compile finalizing fragments
		scored_fragments = []
		seen_content = set()
		for point in candidates:
			if not point.payload: continue

			content = point.payload.get("content", "").strip()
			if not content or point.payload.get("category", "") == "work":
				continue
			if content in seen_content:
				continue

			seen_content.add(content)
			intensity = float(point.payload.get("intensity", 0.0))
			color = point.payload.get("color", "gray")
			created_at = float(point.payload.get("created_at", 0.0))

			score = composite_score(intensity, color, created_at, strategy=scoring_strategy)
			scored_fragments.append({"score": score, "payload": point.payload, "timestamp": created_at})

		top_fragments = scored_fragments
		# Enforce a hard cap just in case
		max_fragments = getattr(config, "PRE_HEATING_MAX_FRAGMENTS", 5)
		top_fragments = top_fragments[:max_fragments]

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
