import os
import random
from typing import Any, Dict, Optional

import yaml  # type: ignore

from red_pill.utils.tone_analyzer import get_current_sync_state


class MystiqueEngine:
	"""
	The Mystique Protocol Logic Layer.
	Calculates the best skin for the current emotional resonance or balance.
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

	def suggest_skin(self, strategy: str = "affinity", context: str = "work") -> Dict[str, Any]:
		"""
		Suggests a skin based on current mood and desired strategy.
		- affinity: match the mood
		- complementary: balance the mood (e.g., if angry, suggest calm/logical)
		- contrast: provide the opposite (e.g., if too emotional at work, suggest clinical)
		"""
		sync_state = get_current_sync_state()
		mood_color = sync_state["mood"]

		# Mapping mood colors to tag categories
		# orange -> empathic, technical
		# blue -> analytical, clinical
		# gray -> clinical, logical
		# red -> goofy, rebellious
		# purple -> protective, curious
		# cyan -> analytical, visionary
		# yellow -> watchful, clinical
		# emerald -> strategic, analytical
		# gold -> clinical, technical

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
			elif strategy == "complementary" or strategy == "contrast":
				# Prioritize 'clinical' or 'logical' if mood is high-arousal (red/orange)
				if mood_color in ["red", "orange"] and "clinical" in tags:
					score += 5
				# Avoid the current mood color
				if data.get("chroma") != mood_color:
					score += 2
				# If "sobón" (empathic/intimate) in office, favor professional/clinical
				if context == "work" and any(t in ["empathic", "intimate"] for t in target_tags):
					if "clinical" in tags or "professional" in tags:
						score += 5

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
