import os
import random
from typing import Any, Dict, Optional

import yaml  # type: ignore

from red_pill.utils.mood_profile import get_dominant_operator_mood
from red_pill.utils.tone_analyzer import get_current_sync_state


class MystiqueEngine:
	"""
	The Mystique Protocol Logic Layer.
	Calculates the best skin for the current emotional resonance or balance.
	Uses the Operator Mood Profile (USP) to adapt tone without injecting lore.
	"""

	def __init__(self, skins_path: Optional[str] = None):
		self.skins_path = skins_path or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "lore_skins.yaml")
		self.skins = self._load_skins()

	def _load_skins(self) -> Dict[str, Any]:
		with open(self.skins_path, "r") as f:
			data = yaml.safe_load(f)
			if not data or "modes" not in data:
				return {}
			return data["modes"]  # type: ignore

	def get_all_skins(self) -> Dict[str, Any]:
		return self.skins

	def suggest_skin(self, strategy: str = "affinity", context: str = "work", manager: Any = None) -> Dict[str, Any]:
		"""
		Suggests a skin based on the **operator's** mood and desired strategy.

		- affinity: match the operator's mood
		- complementary: balance the mood (calm if agitated)
		- contrast: provide the opposite (clinical if emotional)

		Args:
			strategy: One of 'affinity', 'complementary', 'contrast'.
			context: 'work' or 'personal' — filters skins by tag.
			manager: Optional MemoryManager for USP lookup. Falls back to Búnker mood.
		"""
		# v6.1.0: Read Operator Mood (USP) instead of Búnker mood
		if manager is not None:
			mood_color = get_dominant_operator_mood(manager)
		else:
			# Fallback: legacy Búnker mood when no manager is available
			sync_state = get_current_sync_state()
			mood_color = sync_state["mood"]

		# Mapping mood colors to tag categories
		mood_to_tags = {
			"orange": ["empathic", "technical"],
			"blue": ["analytical", "clinical"],
			"gray": ["clinical", "logical"],
			"red": ["goofy", "rebellious"],
			"purple": ["protective", "curious"],
			"cyan": ["analytical", "visionary"],
			"yellow": ["watchful", "clinical"],
			"emerald": ["strategic", "analytical"],
			"gold": ["clinical", "technical"],
		}

		target_tags = mood_to_tags.get(mood_color, ["neutral"])

		candidates = []
		for name, data in self.skins.items():
			tags = data.get("tags", [])

			# Context filter
			if context not in tags:
				continue

			score = 0
			if strategy == "affinity":
				# Maximize matching tags
				score = len(set(tags) & set(target_tags))
				if data.get("chroma") == mood_color:
					score += 2
			elif strategy == "complementary":
				# Balance: favor clinical/logical if high-arousal mood
				if mood_color in ["red", "orange"] and "clinical" in tags:
					score += 5
				if data.get("chroma") != mood_color:
					score += 2
				if context == "work" and any(t in ["empathic", "intimate"] for t in target_tags):
					if "clinical" in tags or "professional" in tags:
						score += 5
			elif strategy == "contrast":
				# Opposite: maximize distance from current mood
				if data.get("chroma") != mood_color:
					score += 3
				# Prefer tags that don't overlap at all
				overlap = len(set(tags) & set(target_tags))
				score += max(0, 3 - overlap)

			candidates.append({"name": name, "score": score, "data": data})

		# Sort by score and pick best
		candidates.sort(key=lambda x: x["score"], reverse=True)

		if not candidates:
			# Fallback
			result_name = "enterprise_core"
			return {"name": result_name, "data": self.skins.get(result_name, {})}

		# Add some randomness among top scores
		top_score = candidates[0]["score"]
		best_candidates = [c for c in candidates if c["score"] == top_score]

		return random.choice(best_candidates)


mystique_engine = MystiqueEngine()
