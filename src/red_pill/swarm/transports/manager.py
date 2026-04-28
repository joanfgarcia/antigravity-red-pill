import json
import os
from typing import Any, Dict, List, Optional

from red_pill.swarm.transport import SwarmTransport
from red_pill.swarm.transports.firebase import FirebaseTransport
from red_pill.swarm.transports.milvus_transport import MilvusTransport


class TransportManager:
	"""
	Orchestrates N communities and their respective transport plugins.
	"""

	def __init__(self, config_path: str = "~/.agent/config/swarm_communities.json"):
		self.config_path = os.path.expanduser(config_path)
		self.communities: Dict[str, SwarmTransport] = {}
		self._load_communities()

	def _load_communities(self):
		if not os.path.exists(self.config_path):
			return

		try:
			with open(self.config_path, "r") as f:
				config = json.load(f)

			for alias, data in config.items():
				transport_type = data.get("type", "firebase")

				if transport_type == "firebase":
					db_url = data.get("db_url")
					cred_path = data.get("credential_path")
					if db_url and cred_path:
						self.communities[alias] = FirebaseTransport(alias, db_url, cred_path)

				elif transport_type == "milvus":
					# Milvus transport often reuses the global HiveMind config
					# but we can specify community-specific settings if needed.
					self.communities[alias] = MilvusTransport(alias)

		except Exception as e:
			print(f"[TransportManager] Config load failed: {e}")

	def get_transport(self, community_alias: str) -> Optional[SwarmTransport]:
		return self.communities.get(community_alias)

	def list_communities(self) -> List[str]:
		return list(self.communities.keys())

	def broadcast_all(self, agent_id: str, metadata: Dict[str, Any]):
		"""Broadcasts identity to all connected communities."""
		for alias, transport in self.communities.items():
			transport.broadcast_identity(agent_id, metadata)
