from typing import Dict, List, Optional

from red_pill.swarm.crypto import SwarmCrypto


class SovereignGroup:
	"""
	Manages a TreeKEM group state for a community.
	Each group has a tree of public keys.
	"""

	def __init__(self, group_id: str):
		self.group_id = group_id
		self.members: Dict[str, bytes] = {} # agent_identity -> public_key
		self.tree_nodes: List[Optional[bytes]] = [] # Binary tree representation

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
					parent = SwarmCrypto.combine_nodes(nodes[i], nodes[i+1])
					next_level.append(parent)
				else:
					next_level.append(nodes[i]) # Odd node propagates up
			nodes = next_level

		self.root_secret = nodes[0]

	def get_group_key(self) -> bytes:
		"""Derives the current encryption key for the group."""
		return SwarmCrypto.derive_group_key([self.root_secret])
