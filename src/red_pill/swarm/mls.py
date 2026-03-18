import logging
from typing import Dict, List, Optional

from red_pill.swarm.crypto import SwarmCrypto

logger = logging.getLogger(__name__)


class SovereignGroup:
	"""
	Manages a TreeKEM group state for a community.
	Each group has a tree of public keys.
	"""

	def __init__(self, group_id: str):
		self.group_id = group_id
		self.members: Dict[str, bytes] = {}  # agent_identity -> public_key
		self.tree_nodes: List[Optional[bytes]] = []  # Binary tree representation
		self.root_secret: Optional[bytes] = None
		self.message_count: int = 0
		self.key_epoch: int = 1
		self.rotation_threshold: int = 100

	def add_member(self, agent_identity: str, public_key: bytes):
		self.members[agent_identity] = public_key
		self._rebuild_tree()

	def _rebuild_tree(self):
		"""
		Simple PoC of TreeKEM rebuilding.
		In a real system, this happens incrementally.
		"""
		pubs = list(self.members.values())
		if not pubs:
			return

		# Building a simple balanced tree from leaves
		nodes = pubs
		while len(nodes) > 1:
			next_level = []
			for i in range(0, len(nodes), 2):
				if i + 1 < len(nodes):
					parent = SwarmCrypto.combine_nodes(nodes[i], nodes[i + 1])
					next_level.append(parent)
				else:
					next_level.append(nodes[i])  # Odd node propagates up
			nodes = next_level

		self.root_secret = nodes[0]

	def get_group_key(self) -> bytes:
		"""Derives the current encryption key for the group based on the current epoch."""
		if not self.root_secret:
			# Fallback if no members have joined yet
			base_secret = SwarmCrypto.derive_group_key([b"empty_group_seed"])
		else:
			base_secret = SwarmCrypto.derive_group_key([self.root_secret])

		# Ratchet the key using the epoch salt
		import hashlib

		ratchet = hashlib.sha256(base_secret + str(self.key_epoch).encode()).digest()
		return ratchet

	def should_rotate(self) -> bool:
		"""Returns True if the group key has exceeded its message threshold."""
		return self.message_count >= self.rotation_threshold

	def rotate_key(self) -> int:
		"""
		Forces a forward ratchet of the group key (Perfect Forward Secrecy).
		Increments the epoch, resets the message counter.
		Returns the new epoch.
		"""
		self.key_epoch += 1
		self.message_count = 0
		return self.key_epoch

	def sync_epoch(self, new_epoch: int):
		"""Fast-forward the local ratchet state if a newer epoch is detected."""
		if new_epoch > self.key_epoch:
			self.key_epoch = new_epoch
			self.message_count = 0

	def increment_message(self):
		"""Tracks encryption ops to trigger automatic ratcheting."""
		self.message_count += 1
