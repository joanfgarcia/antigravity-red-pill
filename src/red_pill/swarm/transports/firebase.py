import hashlib
from typing import Any, Dict, List, Optional

import firebase_admin
from firebase_admin import credentials, db

from red_pill.swarm.transport import SwarmTransport


class FirebaseTransport(SwarmTransport):
	"""
	Firebase implementation of SwarmTransport.
	Uses Realtime Database for identity registry and mailboxes.
	"""

	def __init__(self, community_alias: str, db_url: str, credential_path: str):
		self.community_alias = community_alias
		self.db_url = db_url
		self.credential_path = credential_path
		self._initialize_sdk()

	def _initialize_sdk(self):
		# Initialize individual app per community to avoid conflicts
		app_name = f"swarm_{self.community_alias}"
		try:
			self.app = firebase_admin.get_app(app_name)
		except ValueError:
			cred = credentials.Certificate(self.credential_path)
			self.app = firebase_admin.initialize_app(cred, {"databaseURL": self.db_url}, name=app_name)

	def broadcast_identity(self, agent_id: str, metadata: Dict[str, Any]) -> bool:
		try:
			ref = db.reference(f"registry/{agent_id}", app=self.app)
			ref.set(metadata)
			return True
		except Exception as e:
			print(f"[FirebaseTransport] Broadcast failed: {e}")
			return False

	def send_package(self, target_id: str, package: Dict[str, Any]) -> bool:
		try:
			# Mailbox ID should be readable (e.g. Aleph_Joan) instead of a hash for Swarm V3 logic.
			mailbox_id = target_id.replace("@", "_")
			ref = db.reference(f"mailboxes/{mailbox_id}/inbox", app=self.app)
			ref.push(package)
			return True
		except Exception as e:
			print(f"[FirebaseTransport] Send failed: {e}")
			return False

	def poll_mailbox(self, agent_id: str) -> List[Dict[str, Any]]:
		try:
			mailbox_id = agent_id.replace("@", "_")
			ref = db.reference(f"mailboxes/{mailbox_id}/inbox", app=self.app)
			messages = ref.get()
			if not messages:
				return []

			results = []
			for msg_id, pkg in messages.items():
				pkg["_msg_id"] = msg_id
				results.append(pkg)
			return results
		except Exception as e:
			print(f"[FirebaseTransport] Poll failed: {e}")
			return []

	def lookup_public_key(self, alias: str) -> Optional[str]:
		try:
			ref = db.reference("registry", app=self.app)
			nodes = ref.get()
			if not nodes:
				return None

			for node_id, data in nodes.items():
				if data.get("alias") == alias:
					key = data.get("public_key")
					return str(key) if key else None
			return None
		except Exception as e:
			print(f"[FirebaseTransport] Lookup failed: {e}")
			return None

	def resolve_alias(self, partial_alias: str) -> Optional[tuple[str, str]]:
		try:
			ref = db.reference("registry", app=self.app)
			nodes = ref.get()
			if not nodes:
				return None

			partial_lower = partial_alias.lower()
			for node_id, data in nodes.items():
				full_alias = data.get("alias", "")
				if full_alias and (full_alias.lower() == partial_lower or full_alias.lower().startswith(f"{partial_lower}@")):
					key = data.get("public_key", "")
					return (full_alias, str(key) if key else "")
			return None
		except Exception as e:
			print(f"[FirebaseTransport] Resolve alias failed: {e}")
			return None
