import hashlib
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
		self._bootstrap_group_key()

	def _initialize_sdk(self):
		# Initialize individual app per community to avoid conflicts
		app_name = f"swarm_{self.community_alias}"
		try:
			self.app = firebase_admin.get_app(app_name)
		except ValueError:
			cred = credentials.Certificate(self.credential_path)
			self.app = firebase_admin.initialize_app(cred, {"databaseURL": self.db_url}, name=app_name)

	def _bootstrap_group_key(self):
		"""Derive group encryption key from all members' public keys in registry."""
		try:
			from red_pill.swarm.crypto import SwarmCrypto
			from red_pill.swarm.mls import SovereignGroup

			ref = db.reference("registry", app=self.app)
			nodes = ref.get()
			if not nodes:
				logger.warning("[MLS] No registry nodes found — group key unavailable")
				return

			group = SovereignGroup(self.community_alias)
			import base64

			for node_id, data in nodes.items():
				alias = data.get("alias", node_id)
				pub_key_b64 = data.get("public_key")
				if pub_key_b64:
					try:
						pub_bytes = base64.b64decode(pub_key_b64)
						group.add_member(alias, pub_bytes)
					except Exception:
						logger.warning(f"[MLS] Skipping member {alias}: invalid public key")

			if group.members and hasattr(group, "root_secret"):
				self._group_key = SwarmCrypto.derive_group_key([group.root_secret])
				logger.info(f"[MLS] Group key derived for '{self.community_alias}' ({len(group.members)} members)")
			else:
				logger.warning("[MLS] Not enough members for group key derivation")

		except Exception as e:
			logger.warning(f"[MLS] Group key bootstrap failed: {e}")

	def broadcast_identity(self, agent_id: str, metadata: Dict[str, Any]) -> bool:
		try:
			ref = db.reference(f"registry/{agent_id}", app=self.app)
			ref.set(metadata)
			# Rebuild group key after identity broadcast (new member may have joined)
			self._bootstrap_group_key()
			return True
		except Exception as e:
			logger.error(f"[FirebaseTransport] Broadcast failed: {e}")
			return False

	def send_package(self, target_id: str, package: Dict[str, Any]) -> bool:
		try:
			# Encrypt if group key is available
			if self._group_key:
				from red_pill.swarm.crypto import SwarmCrypto

				encrypted = SwarmCrypto.encrypt_payload(package, self._group_key)
				payload = encrypted  # Contains: v, nonce, ciphertext
			else:
				payload = package  # Fallback: plaintext (legacy)

			mailbox_id = hashlib.sha256(target_id.encode()).hexdigest()[:24]
			ref = db.reference(f"mailboxes/{mailbox_id}/inbox", app=self.app)
			ref.push(payload)
			return True
		except Exception as e:
			logger.error(f"[FirebaseTransport] Send failed: {e}")
			return False

	def poll_mailbox(self, agent_id: str) -> List[Dict[str, Any]]:
		try:
			mailbox_id = hashlib.sha256(agent_id.encode()).hexdigest()[:24]
			ref = db.reference(f"mailboxes/{mailbox_id}/inbox", app=self.app)
			messages = ref.get()
			if not messages:
				return []

			results = []
			for msg_id, pkg in messages.items():
				pkg["_msg_id"] = msg_id
				# Decrypt if encrypted (v:2 marker)
				if isinstance(pkg.get("v"), int) and pkg["v"] >= 2 and "ciphertext" in pkg:
					if self._group_key:
						try:
							from red_pill.swarm.crypto import SwarmCrypto

							decrypted = SwarmCrypto.decrypt_payload(pkg, self._group_key)
							decrypted["_msg_id"] = msg_id
							decrypted["_encrypted"] = True
							results.append(decrypted)
						except Exception as e:
							logger.warning(f"[MLS] Decrypt failed for {msg_id}: {e}")
							pkg["_decrypt_error"] = str(e)
							results.append(pkg)
					else:
						pkg["_decrypt_error"] = "No group key available"
						results.append(pkg)
				else:
					# Legacy plaintext message
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
