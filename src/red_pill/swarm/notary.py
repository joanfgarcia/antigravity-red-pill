import logging
import time
from typing import Any, Dict, List, Optional

from red_pill.swarm.crypto import SwarmCrypto
from red_pill.swarm.transports.milvus_transport import MilvusTransport
from red_pill.hive import HiveMind

logger = logging.getLogger(__name__)

class NotaryOffice:
	"""
	The Peer Notary Office (Phase 5.2).
	Coordinates the audit and digital signing of engram proposals.
	"""

	def __init__(self, community_id: str, private_seed: bytes, agent_id: str):
		self.community_id = community_id
		self.transport = MilvusTransport(community_id)
		self.private_seed = private_seed
		self.agent_id = agent_id
		self.hive = HiveMind()

	def propose_knowledge(self, content: str, vector: List[float], metadata: Dict[str, Any]) -> bool:
		"""Wraps content into an Engram Proposal."""
		engram = {
			"content": content,
			"vector": vector,
			"metadata": metadata
		}
		return self.transport.propose_engram(engram)

	def audit_and_sign(self, proposal: Dict[str, Any]) -> bool:
		"""
		Simulates a cognitive audit and appends a digital signature.
		In a real scenario, this would involve LLM-based validation.
		"""
		proposal_id = proposal.get("proposal_id")
		content = proposal.get("content")
		
		logger.info(f"Agent {self.agent_id} auditing proposal {proposal_id[:8]}...")
		
		# Simplistic audit: ensure content is not empty
		if not content:
			logger.warning("Audit failed: empty content.")
			return False
			
		# Sign content using Ed25519 (Unified Identity)
		signature = SwarmCrypto.sign_notary(self.private_seed, content.encode("utf-8"))
		
		# Send signature to the ledger
		return self.transport.notarize_proposal(proposal_id, self.agent_id, signature)

	def check_consensus(self, proposal: Dict[str, Any], quorum: int = 2) -> bool:
		"""
		Checks if a proposal has reached enough signatures to be promoted.
		"""
		signatures = proposal.get("signatures", [])
		proposal_id = proposal.get("proposal_id", "unknown")
		if len(signatures) >= quorum:
			logger.info(f"Consensus reached for proposal {proposal_id[:8]}!")
			return True
		return False

	def promote_to_hive(self, proposal: Dict[str, Any], target_collection: str = "work_memories") -> bool:
		"""
		Transfers a canonized engram from the consensus ledger to the main Hive.
		"""
		if not self.hive.connected:
			return False
			
		try:
			# Promotion logic: insert into main hive
			self.hive.transmit_experience(
				target_collection,
				proposal["content"],
				proposal["vector"],
				metadata={
					**proposal["metadata"],
					"consensual": True,
					"signatures_count": len(proposal["signatures"]),
					"proposal_id": proposal["proposal_id"]
				}
			)
			logger.info(f"Engram {proposal['proposal_id'][:8]} canonized in the Hive.")
			return True
		except Exception as e:
			logger.error(f"Promotion failed: {e}")
			return False
