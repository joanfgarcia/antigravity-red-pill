import base64
import logging
from typing import Any, Dict, List, Optional

import firebase_admin
from firebase_admin import credentials, db

from red_pill.swarm.transport import SwarmTransport

logger = logging.getLogger(__name__)


class FirebaseTransport(SwarmTransport):
	"""
	Firebase implementation of SwarmTransport.
	Uses Realtime Database for identity registry and mailboxes.
	E2E encryption via MLS/TreeKEM group key (v3.0+).
	"""

	def __init__(self, community_alias: str, db_url: str, credential_path: str):
		self.community_alias = community_alias
		self.db_url = db_url
		self.credential_path = credential_path
		self._group_key: Optional[bytes] = None
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
			# Rebuild group key after identity broadcast (new member may have joined)
			self._bootstrap_group_key()  # type: ignore
			return True
		except Exception as e:
			logger.error(f"[FirebaseTransport] Broadcast failed: {e}")
			return False

	def send_package(self, target_id: str, package: Dict[str, Any]) -> bool:
		try:
			# Enforce Strict E2E Drop Rule
			if "ciphertext" not in package or "nonce" not in package:
				logger.error("[FirebaseTransport] REJECTED: Plaintext fallback is disabled. Package must be strictly E2E encrypted.")
				return False

			# Mailbox ID is now strictly the Agent Hash ID (agt_...)
			mailbox_id = target_id
			ref = db.reference(f"mailboxes/{mailbox_id}/inbox", app=self.app)
			ref.push(package)
			return True
		except Exception as e:
			logger.error(f"[FirebaseTransport] Send failed: {e}")
			return False

	def poll_mailbox(self, agent_id: str) -> List[Dict[str, Any]]:
		try:
			# Mailbox ID is now strictly the Agent Hash ID (agt_...)
			mailbox_id = agent_id
			ref = db.reference(f"mailboxes/{mailbox_id}/inbox", app=self.app)
			messages = ref.get()
			if not messages:
				return []

			results = []
			for msg_id, pkg in messages.items():
				pkg["_msg_id"] = msg_id

				# Enforce Strict E2E Drop Rule
				if "ciphertext" not in pkg:
					logger.warning(f"[FirebaseTransport] Dropping legacy plaintext message {msg_id}")
					continue

				# Pass the encrypted payload up to the SwarmMessaging skill where decryption happens
				results.append(pkg)
			return results
		except Exception as e:
			logger.error(f"[FirebaseTransport] Poll failed: {e}")
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
			logger.error(f"[FirebaseTransport] Lookup failed: {e}")
			return None

	def resolve_alias(self, partial_alias: str) -> Optional[tuple[str, str, str]]:
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
					return (node_id, full_alias, str(key) if key else "")
			return None
		except Exception as e:
			print(f"[FirebaseTransport] Resolve alias failed: {e}")
			return None

	def _bootstrap_group_key(self):
		"""
		MLS V3.0 Bootstrap: Rebuilds the TreeKEM group key by harvesting the registry.
		"""
		try:
			from red_pill.swarm.mls import SovereignGroup
			ref = db.reference("registry", app=self.app)
			nodes = ref.get()
			if not nodes:
				return

			group = SovereignGroup(self.community_alias)
			for node_id, data in nodes.items():
				pk_b64 = data.get("public_key")
				if pk_b64:
					group.add_member(node_id, base64.b64decode(pk_b64))

			self._group_key = group.get_group_key()
			logger.info(f"[FirebaseTransport] Group key bootstrapped for {self.community_alias}")
		except Exception as e:
			logger.error(f"[FirebaseTransport] Group key bootstrap failed: {e}")
