import base64
import logging
import os
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
		self.mls_group: Optional[Any] = None
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

	def resolve_alias(self, partial_alias: str) -> Optional[tuple[str, str, str, str]]:
		"""
		Resolves a partial alias to (agent_id, full_alias, public_key_b64, key_package_b64).
		Drops entries with invalid admission_token (HMAC guard).
		"""
		try:
			ref = db.reference("registry", app=self.app)
			nodes = ref.get()
			if not nodes:
				return None

			shared_secret = os.getenv("SWARM_SHARED_SECRET", "").encode()
			partial_lower = partial_alias.lower()

			for node_id, data in nodes.items():
				full_alias = data.get("alias", "")
				if not full_alias:
					continue
				if not (full_alias.lower() == partial_lower or full_alias.lower().startswith(f"{partial_lower}@")):
					continue

				# MLS B1: Verify admission token if present
				kp_b64 = data.get("key_package", "")
				admission_token = data.get("admission_token", "")
				if kp_b64 and admission_token and shared_secret:
					import hashlib
					import hmac as _hmac

					kp_bytes = base64.b64decode(kp_b64)
					expected = base64.b64encode(
						_hmac.new(shared_secret, kp_bytes, hashlib.sha256).digest()
					).decode()
					if not _hmac.compare_digest(expected, admission_token):
						logger.warning(f"[FirebaseTransport] Invalid admission_token for '{full_alias}'. Dropping.")
						continue

				pk = data.get("public_key", "")
				return (node_id, full_alias, str(pk) if pk else "", kp_b64)
			return None
		except Exception as e:
			logger.error(f"[FirebaseTransport] Resolve alias failed: {e}")
			return None

	def push_welcome(self, target_id: str, welcome_bytes: bytes) -> bool:
		"""Deposits an MLS Welcome message into the target's welcome slot."""
		try:
			ref = db.reference(f"mls_welcomes/{target_id}", app=self.app)
			ref.set(base64.b64encode(welcome_bytes).decode("utf-8"))
			logger.info(f"[FirebaseTransport] Welcome pushed to '{target_id}'.")
			return True
		except Exception as e:
			logger.error(f"[FirebaseTransport] push_welcome failed: {e}")
			return False

	def pop_welcome(self, my_id: str) -> Optional[bytes]:
		"""Reads and deletes the MLS Welcome for this agent (destructive read)."""
		try:
			ref = db.reference(f"mls_welcomes/{my_id}", app=self.app)
			value = ref.get()
			if not value:
				return None
			ref.delete()
			return base64.b64decode(value)
		except Exception as e:
			logger.error(f"[FirebaseTransport] pop_welcome failed: {e}")
			return None

	# _bootstrap_group_key() removed — SovereignGroup replaced by pure-mls MLSBridge.
