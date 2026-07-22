import logging
import time

from qdrant_client import models

from red_pill import config
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.utils.pre_heating_scorer import composite_score, extract_contextual_metadata

logger = logging.getLogger(__name__)

MAX_TRACKED_PROJECTS = getattr(config, "PRE_HEATING_MAX_TRACKED_PROJECTS", 3)


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
		from red_pill.interceptors import _05_cognitive_router_state as _cr_state

		if _cr_state.is_casual_active():
			return ""

		if self.__class__._has_fired:
			return ""

		from red_pill.memory import MemoryManager

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
				valid_social = [p for p in valid_social if p.payload and p.payload.get("category", "") != "work"]

				# Sort by timestamp DESC (most recent first)
				valid_social.sort(key=lambda x: float(x.payload.get("created_at", 0)) if x.payload else 0.0, reverse=True)

				# --- HIPPOCAMPUS (Continuity): Top 2 most recent regardless of color ---
				hippocampus = valid_social[:2]
				candidates.extend(hippocampus)

				# --- AMYGDALA (Emotional Anchors): Top 3 most intense with hot colors ---
				hippo_ids = {p.id for p in hippocampus}
				potential_amygdala = [p for p in valid_social if p.id not in hippo_ids]
				potential_amygdala = [p for p in potential_amygdala if p.payload and p.payload.get("color", "gray") in colors]

				# Score Amygdala candidates
				for p in potential_amygdala:
					intensity = float(p.payload.get("intensity", 0.0)) if p.payload else 0.0
					color = str(p.payload.get("color", "gray")) if p.payload else "gray"
					created_at = float(p.payload.get("created_at", 0.0)) if p.payload else 0.0
					setattr(p, "_temp_score", composite_score(intensity, color, created_at, strategy=scoring_strategy))

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
			if not point.payload:
				continue

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
			self.__class__._has_fired = True
			return ""

		parts = []
		parts.append("=== EMOTIONAL PRE-HEATING (ORACLE PROTOCOL) ===")
		parts.append("SESSION_CONTINUITY: Your emotional thread with the Operator is injected below.")
		parts.append("Do not repeat these themes verbatim — let them inform your tone implicitly.")

		for idx, frag in enumerate(top_fragments, 1):
			score = float(str(frag.get("score", 0.0)))
			color = str(frag["payload"].get("color", "gray")) if isinstance(frag["payload"], dict) else "gray"
			age_hours = round((now - float(str(frag.get("timestamp", 0.0)))) / 3600, 1)

			parts.append(f"\n[MEMORY_{idx} — {color}, score={score}, {age_hours}h ago]")

			if injection_mode == "contextual":
				meta = extract_contextual_metadata(dict(frag["payload"])) if isinstance(frag["payload"], dict) else extract_contextual_metadata({})
				parts.append(f"  Themes: {', '.join(meta['themes']) if meta['themes'] else 'unspecified'}")
				parts.append(f"  Tone: {meta['tone']}")
				parts.append(f"  Operator state: {meta['operator_state']}")
			else:
				payload = frag["payload"]
				raw_text = payload.get("content", "") if isinstance(payload, dict) else ""
				max_chars = getattr(config, "PRE_HEATING_MAX_CHARS_PER_FRAGMENT", 200)
				if len(raw_text) > max_chars:
					raw_text = raw_text[:max_chars] + "..."
				parts.append(f"  Content: {repr(raw_text)}")

		parts.append(f"\nCALIBRATION: Quality threshold is {quality_threshold}. Material is reliable.")
		parts.append("---")

		# ── PROJECT STATUS (tracked workspaces) ──
		try:
			from red_pill.core.workspaces import list_tracked_workspaces

			tracked = list_tracked_workspaces()[:MAX_TRACKED_PROJECTS]
			if tracked:
				parts.append("\n=== PROJECT STATUS ===")
				for ws in tracked:
					try:
						if client.collection_exists("work_memories"):
							results, _ = client.scroll(
								collection_name="work_memories",
								scroll_filter=models.Filter(must=[models.FieldCondition(key="workspace", match=models.MatchValue(value=ws.name))]),
								limit=3,
								with_payload=True,
							)
							recent = [p.payload.get("content", "") for p in results if p.payload and p.payload.get("content")]
							if recent:
								parts.append(f"[{ws.name}] Recent: {'; '.join(r[:80] for r in recent[:2])}")
							else:
								parts.append(f"[{ws.name}] No recent work memories")
						else:
							parts.append(f"[{ws.name}] work_memories collection not available")
					except Exception as e:
						logger.debug(f"Project status query failed for {ws.name}: {e}")
						parts.append(f"[{ws.name}] Query failed")
		except Exception as e:
			logger.debug(f"Project status enumeration failed: {e}")

		# ── RECENT WORK (cascading fallback) ──
		try:
			recent_work = self._query_recent_work(client, now)
			if recent_work:
				parts.append("\n=== RECENT WORK ===")
				parts.append(recent_work)
		except Exception as e:
			logger.debug(f"Recent work query failed: {e}")

		# Mark as fired so it doesn't trigger on subsequent turns
		self.__class__._has_fired = True
		return "\n".join(parts)

	def _query_recent_work(self, client, now: float) -> str:
		"""Query recent work with cascading fallback: work_memories → interaction_memories → omit."""
		# Tier 1: work_memories (last 7 days)
		try:
			if client.collection_exists("work_memories"):
				cutoff = now - (7 * 24 * 3600)
				results, _ = client.scroll(
					collection_name="work_memories",
					scroll_filter=models.Filter(must=[models.FieldCondition(key="created_at", range=models.Range(gte=cutoff))]),
					limit=3,
					with_payload=True,
				)
				recent = [p.payload.get("content", "") for p in results if p.payload and p.payload.get("content")]
				if recent:
					return "Work: " + "; ".join(r[:100] for r in recent)
		except Exception as e:
			logger.debug(f"work_memories fallback failed: {e}")

		# Tier 2: interaction_memories (last 48h, work category)
		try:
			if client.collection_exists("interaction_memories"):
				cutoff = now - (48 * 3600)
				results, _ = client.scroll(
					collection_name="interaction_memories",
					scroll_filter=models.Filter(
						must=[
							models.FieldCondition(key="created_at", range=models.Range(gte=cutoff)),
							models.FieldCondition(key="category", match=models.MatchValue(value="work")),
						]
					),
					limit=3,
					with_payload=True,
				)
				recent = [p.payload.get("content", "") for p in results if p.payload and p.payload.get("content")]
				if recent:
					return "Recent sessions: " + "; ".join(r[:100] for r in recent)
		except Exception as e:
			logger.debug(f"interaction_memories fallback failed: {e}")

		return ""
