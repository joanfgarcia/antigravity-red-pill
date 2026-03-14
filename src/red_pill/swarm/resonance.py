import logging
from typing import Any, Dict, List, Optional

import red_pill.config as cfg
from red_pill.hive import HiveMind

logger = logging.getLogger(__name__)

class ResonanceObserver:
	"""
	The Semantic Radar.
	Monitors the Hive Mind for engrams that resonate with specific cognitive hubs.
	"""

	def __init__(self, agent_id: str):
		self.agent_id = agent_id
		self.hive = HiveMind()

	def check_resonance(self, hub_vector: List[float], collection_name: str = "work_memories") -> List[Dict[str, Any]]:
		"""
		Searches for engrams in the Hive that are semantically close to the hub_vector.
		"""
		if not self.hive.connected:
			return []

		try:
			# Search with a strict threshold
			# Milvus distance (L2): lower is closer
			experiences = self.hive.sync_from_hive(
				query_vector=hub_vector,
				collection_name=collection_name,
				limit=5
			)

			resonating = []
			for exp in experiences:
				distance = exp.get("distance", 1.0)
				if distance <= cfg.RESONANCE_THRESHOLD:
					# Skip own messages if necessary
					if exp.get("source_agent") == self.agent_id:
						continue
						
					logger.info(f"✨ Resonance detected (d={distance:.4f}): {exp['content'][:50]}...")
					resonating.append(exp)

			return resonating
		except Exception as e:
			logger.error(f"Resonance search failed: {e}")
			return []

	def trigger_reaction(self, match: Dict[str, Any]):
		"""
		Executes a proactive response to a resonating engram.
		"""
		content = match.get("content", "")
		source = match.get("source_agent", "unknown")
		
		# Proactive Notification logic
		# In a full UI impl, this would push to a dashboard.
		logger.info(f"Cognitive Trigger: Reacting to intelligence from {source}.")
		# Simulating an internal "thought" recording
		# (Agentic self-talk would go here)
