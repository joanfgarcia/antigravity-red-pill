"""
Operator Mood Profile (USP — User Status Profile).

Captures the operator's emotional resonance as a multi-color vector
across temporal horizons (Global, 30d, 7d, 3d).

Aggregation formula (per horizon):
	1. Query work_memories + social_memories for engrams within window t
	2. Group by color (chroma)
	3. Weight each engram: weight = intensity * importance
	4. Normalize per-color to get Resonance Vector R_t
"""

import logging
import time
from typing import Any, Dict, List, Optional

from qdrant_client.http import models

import red_pill.config as cfg

logger = logging.getLogger(__name__)

ID_OPERATOR_MOOD = "00000000-0000-0000-0000-000000000060"

CHROMA_KEYS = ["orange", "yellow", "purple", "cyan", "blue", "gray", "red", "emerald", "gold"]

HORIZONS: Dict[str, float] = {
	"last_3d": 3 * 86400,
	"last_7d": 7 * 86400,
	"last_30d": 30 * 86400,
	"global": 0,  # 0 = no time filter
}

SOURCE_COLLECTIONS = ["work_memories", "social_memories"]


def _empty_vector() -> Dict[str, float]:
	"""Returns a zeroed chroma vector."""
	return {k: 0.0 for k in CHROMA_KEYS}


def calculate_resonance_vector(
	manager: Any,
	horizon_seconds: float,
) -> Dict[str, float]:
	"""
	Calculates the Resonance Vector R_t for a given time horizon.

	Queries work_memories + social_memories, groups by color,
	weights by intensity × importance, and normalizes.
	"""
	now = time.time()
	vector = _empty_vector()
	total_weight = 0.0

	for collection in SOURCE_COLLECTIONS:
		# Build time filter (skip for global — no time limit)
		must_conditions: List[models.Condition] = [
			models.FieldCondition(key="immune", match=models.MatchValue(value=False)),
		]
		if horizon_seconds > 0:
			cutoff = now - horizon_seconds
			must_conditions.append(
				models.FieldCondition(key="created_at", range=models.Range(gte=cutoff)),
			)

		scroll_filter = models.Filter(must=must_conditions)
		offset = None
		safety = 0
		max_scroll = getattr(cfg, "MOOD_PROFILE_MAX_SCROLL", 50)

		while safety < max_scroll:
			safety += 1
			try:
				points, offset = manager.client.scroll(
					collection_name=collection,
					scroll_filter=scroll_filter,
					limit=200,
					offset=offset,
					with_payload=True,
					with_vectors=False,
				)
			except Exception as e:
				logger.warning(f"USP scroll failed for {collection}: {e}")
				break

			for p in points:
				if not p.payload:
					continue
				color = p.payload.get("color", cfg.DEFAULT_COLOR)
				if color not in CHROMA_KEYS:
					continue
				intensity = float(p.payload.get("intensity", 1.0))
				importance = float(p.payload.get("importance", 1.0))
				weight = intensity * importance
				vector[color] += weight
				total_weight += weight

			if offset is None:
				break

		if safety >= max_scroll and offset is not None:
			logger.warning(
				f"PERF-001: calculate_resonance_vector hit the maximum scroll pagination ceiling ({max_scroll}) "
				f"for '{collection}'. The computed emotional mood vector may be truncated."
			)

	# Normalize to [0, 1]
	if total_weight > 0:
		for k in CHROMA_KEYS:
			vector[k] = round(vector[k] / total_weight, 4)

	return vector


def update_usp(manager: Any) -> Dict[str, Any]:
	"""
	Recalculates all 4 USP horizons and upserts to the fixed engram.

	Returns the full USP payload.
	"""
	usp: Dict[str, Any] = {
		"type": "operator_mood_profile",
		"interaction_count": 0,
		"last_updated": time.time(),
	}

	# Try to read current interaction_count
	try:
		existing = manager.client.retrieve("social_memories", ids=[ID_OPERATOR_MOOD], with_payload=True, with_vectors=False)
		if existing and existing[0].payload:
			usp["interaction_count"] = int(existing[0].payload.get("interaction_count", 0)) + 1
		else:
			usp["interaction_count"] = 1
	except Exception:
		usp["interaction_count"] = 1

	# Calculate each horizon
	for horizon_name, seconds in HORIZONS.items():
		usp[horizon_name] = calculate_resonance_vector(manager, seconds)

	# Upsert to the fixed engram
	try:
		manager.add_memory(
			collection="social_memories",
			text=f"Operator Mood Profile (USP). Last updated: {time.strftime('%Y-%m-%d %H:%M')}. "
			f"Dominant 3d: {get_dominant_operator_mood(manager, usp)}.",
			importance=10.0,
			metadata=usp,
			color=_get_dominant_color(usp.get("last_3d", {})),
			force_immune=True,
			point_id=ID_OPERATOR_MOOD,
		)
	except Exception as e:
		logger.error(f"Failed to persist USP: {e}")

	return usp


def get_operator_mood(
	manager: Any,
	horizon: str = "last_3d",
) -> Dict[str, float]:
	"""
	Reads the current operator mood vector for a given horizon.

	Args:
		manager: MemoryManager instance.
		horizon: One of 'global', 'last_30d', 'last_7d', 'last_3d'.

	Returns:
		Chroma vector dict, or empty vector if not found.
	"""
	try:
		points = manager.client.retrieve("social_memories", ids=[ID_OPERATOR_MOOD], with_payload=True, with_vectors=False)
		if points and points[0].payload:
			result: Dict[str, float] = points[0].payload.get(horizon, _empty_vector())
			return result
	except Exception as e:
		logger.warning(f"Failed to read USP: {e}")
	return _empty_vector()


def get_dominant_operator_mood(
	manager: Any,
	usp: Optional[Dict[str, Any]] = None,
) -> str:
	"""
	Returns the single dominant chroma from the last_3d horizon.

	Args:
		manager: MemoryManager instance.
		usp: Optional pre-loaded USP dict (avoids extra DB read).
	"""
	if usp is not None:
		vector = usp.get("last_3d", _empty_vector())
	else:
		vector = get_operator_mood(manager, "last_3d")

	return _get_dominant_color(vector)


def _get_dominant_color(vector: Dict[str, float]) -> str:
	"""Returns the color with the highest weight, excluding gray."""
	if not vector:
		return str(cfg.DEFAULT_COLOR)

	# Filter out gray (neutral) for dominance calculation
	candidates = {k: v for k, v in vector.items() if k != "gray" and v > 0}
	if not candidates:
		return str(cfg.DEFAULT_COLOR)

	return str(max(candidates, key=candidates.get))  # type: ignore[arg-type]
