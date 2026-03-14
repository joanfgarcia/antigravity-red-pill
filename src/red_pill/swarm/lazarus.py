import json
import logging
import os
import time
from typing import Any, Dict, List

import red_pill.config as cfg

logger = logging.getLogger(__name__)

class LamportClock:
	"""
	A simple Lamport Timestamp implementation for causal ordering.
	"""
	def __init__(self, agent_id: str):
		self.agent_id = agent_id
		self.state_file = cfg.LAZARUS_STATE_FILE
		self.counter = self._load_state()

	def _load_state(self) -> int:
		if os.path.exists(self.state_file):
			try:
				with open(self.state_file, "r") as f:
					data = json.load(f)
					return data.get(self.agent_id, 0)
			except Exception as e:
				logger.error(f"Lazarus: Failed to load clock state: {e}")
		return 0

	def _save_state(self):
		try:
			data = {}
			if os.path.exists(self.state_file):
				with open(self.state_file, "r") as f:
					data = json.load(f)

			data[self.agent_id] = self.counter
			with open(self.state_file, "w") as f:
				json.dump(data, f)
		except Exception as e:
			logger.error(f"Lazarus: Failed to save clock state: {e}")

	def tick(self) -> int:
		"""Increments the local clock."""
		self.counter += 1
		self._save_state()
		return self.counter

	def update(self, remote_timestamp: int):
		"""Synchronizes with a remote timestamp."""
		self.counter = max(self.counter, remote_timestamp) + 1
		self._save_state()

class LazarusSync:
	"""
	Orchestrates the 'Resurrection' of engrams from local dock to global Hive.
	"""

	def __init__(self, community_id: str, agent_id: str):
		self.community_id = community_id
		self.agent_id = agent_id
		self.clock = LamportClock(agent_id)

	def prepare_engram(self, content: str, vector: List[float], metadata: Dict[str, Any]) -> Dict[str, Any]:
		"""Packages an engram with a Lamport Timestamp."""
		timestamp = self.clock.tick()
		return {
			"content": content,
			"vector": vector,
			"metadata": {
				**metadata,
				"lamport_ts": timestamp,
				"source_agent": self.agent_id
			}
		}

	def vacuum(self) -> int:
		"""
		Scans local dock for pending engrams and moves them to the Hive.
		"""
		from pymilvus import Collection, utility

		from red_pill.hive import HiveMind

		logger.info(f"Lazarus: Initiating vacuum for {self.agent_id} in {self.community_id}")

		hive = HiveMind()
		if not hive.connected:
			logger.debug("Lazarus: Hive Mind not reachable. Sync deferred.")
			return 0

		proposal_coll = f"swarm_proposals_{self.community_id}"
		if not utility.has_collection(proposal_coll):
			return 0

		try:
			col = Collection(proposal_coll)
			# Find engrams that are PENDING and have reached quorum (for Ph5.2 logic)
			# Or simply find engrams that haven't been synced yet.
			# For Phase 6, we focus on moving CANONIZED or PENDING ones that are ready.

			res = col.query(
				expr='status == "PENDING"',
				output_fields=["pk", "proposal_id", "content", "vector", "metadata", "signatures"],
				limit=100
			)

			if not res:
				return 0

			count = 0
			for row in res:
				# 1. Check if it's a social/work engram prepared for the hive
				# In a full implementation, we'd check if enough signatures exist (Phase 5.2)
				# For this sync, we'll assume any PENDING engram is a candidate for "lifting"

				# 2. Transmit to Hive
				target_coll = row["metadata"].get("target_collection", "work_memories")

				# Preserve Lamport order: if remote hive has a higher TS, we should update local.
				# (In a real distributed system, we'd query the Hive's latest TS first).

				hive.transmit_experience(
					target_coll,
					row["content"],
					row["vector"],
					metadata={
						**row["metadata"],
						"resurrected": True,
						"original_proposal": row["proposal_id"],
						"signatures_count": len(row["signatures"])
					}
				)

				# 3. Mark as CANONIZED in local dock
				col.delete(expr=f"pk == {row['pk']}")
				# Re-insert with CANONIZED status
				data = [
					[row["proposal_id"]],
					[row["content"]],
					[row["vector"]],
					[row["metadata"]],
					[row["signatures"]],
					["CANONIZED"],
					[int(time.time())] # This would require 'import time' in the file
				]
				col.insert(data)
				count += 1

			col.flush()
			logger.info(f"Lazarus: Successfully resurrected {count} engrams.")
			return count
		except Exception as e:
			logger.error(f"Lazarus: Vacuum failed: {e}")
			return 0
