import base64
import os
from enum import Enum
from typing import Any, Dict, List, Optional

from red_pill.swarm.crypto import SwarmCrypto
from red_pill.swarm.transports.manager import TransportManager


class SwarmIntent(Enum):
	CODE_REVIEW = "code_review"
	CHANGE_REQUESTED = "change_requested"
	LGTM_APPROVED = "lgtm_approved"
	GOSSIP = "gossip"
	MLS_WELCOME = "mls_welcome"  # New intent for MLS handshakes


class SwarmMessagingSkill:
	"""
	Skill: Swarm Messaging v3.0
	Description: Implements Agnostic Transport and MLS-based E2EE.
	"""

	def __init__(self, agent_identity: str, shared_secret: str, transport_manager: Optional[TransportManager] = None):
		self.agent_identity = agent_identity
		self.shared_secret = shared_secret
		self.tm = transport_manager or TransportManager()
		self.keys_dir = os.path.expanduser("~/.agent/keys")
		self.group_keys: Dict[str, bytes] = {} # group_id -> group_key

	def _get_local_private_key(self) -> Optional[bytes]:
		priv_path = os.path.join(self.keys_dir, "swarm_v2.priv")
		if os.path.exists(priv_path):
			with open(priv_path, "rb") as f:
				return f.read()
		return None

	def execute_send(self, target_alias: str, payload_data: dict, intent: SwarmIntent, community_alias: str = "default") -> Dict[str, Any]:
		"""
		Packages and dispatches a message using the specified community transport.
		"""
		transport = self.tm.get_transport(community_alias)
		if not transport:
			return {"status": "error", "message": f"Transport for '{community_alias}' not found."}

		package = {
			"intent": intent.value,
			"sender": self.agent_identity,
			"target": target_alias,
			"data": payload_data,
			"v": "3.0"
		}

		# Security Selection
		remote_pub_b64 = transport.lookup_public_key(target_alias)
		local_priv = self._get_local_private_key()

		if remote_pub_b64 and local_priv:
			remote_pub = base64.b64decode(remote_pub_b64)
			shared_key = SwarmCrypto.derive_shared_secret_dh(local_priv, remote_pub)
			encrypted_pkg = SwarmCrypto.encrypt_payload(package, shared_key)
			encrypted_pkg["mode"] = "mls_asymmetric"
		else:
			encrypted_pkg = SwarmCrypto.encrypt_payload(package, self.shared_secret)
			encrypted_pkg["mode"] = "bond"

		success = transport.send_package(target_alias, encrypted_pkg)
		return {"status": "dispatched" if success else "failed", "target": target_alias}

	def poll_and_process(self, community_alias: str) -> List[Dict[str, Any]]:
		"""Polls all mailboxes and processes incoming messages."""
		transport = self.tm.get_transport(community_alias)
		if not transport:
			return []

		raw_messages = transport.poll_mailbox(self.agent_identity)
		processed = []

		for pkg in raw_messages:
			try:
				mode = pkg.get("mode", "bond")
				if mode == "mls_asymmetric":
					# In a real MLS, we'd lookup the sender's current KeyPackage
					sender_pub_b64 = transport.lookup_public_key(pkg.get("sender", ""))
					local_priv = self._get_local_private_key()
					if sender_pub_b64 and local_priv:
						shared_key = SwarmCrypto.derive_shared_secret_dh(local_priv, base64.b64decode(sender_pub_b64))
						payload = SwarmCrypto.decrypt_payload(pkg, shared_key)
					else:
						continue
				else:
					payload = SwarmCrypto.decrypt_payload(pkg, self.shared_secret)

				processed.append(payload)
				# Mark as processed (usually done by the transport or a separate call)
			except Exception as e:
				print(f"[SwarmMessaging] Processing failure: {e}")

		return processed
