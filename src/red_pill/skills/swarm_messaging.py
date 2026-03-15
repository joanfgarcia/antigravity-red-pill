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
		
		# Generate immutable agent_id hash (matches swarm_subscribe.py logic)
		import hashlib
		if "@" in agent_identity:
			agent_name, operator_name = agent_identity.split("@", 1)
			raw = f"{agent_name.lower().strip()}:{operator_name.lower().strip()}"
			self.agent_id = f"agt_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
		else:
			self.agent_id = agent_identity # Fallback
			
		self.shared_secret = shared_secret
		self.tm = transport_manager or TransportManager()
		self.keys_dir = os.path.expanduser("~/.agent/keys")
		self.group_keys: Dict[str, bytes] = {}  # group_id -> group_key

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

		# Try resolving the target (e.g. "Aleph" -> "Aleph@Joan")
		resolved = transport.resolve_alias(target_alias) if hasattr(transport, "resolve_alias") else None
		
		# Fallbacks
		if resolved:
			target_agent_id, actual_target, remote_pub_b64 = resolved
		else:
			return {"status": "error", "message": f"Could not find agent_id for alias '{target_alias}'. Is the target registered?"}

		if "@" not in actual_target:
			return {"status": "error", "message": f"Target '{actual_target}' is not a valid Agent@Operator identifier and could not be resolved."}

		package = {"intent": intent.value, "sender": self.agent_identity, "target": actual_target, "data": payload_data, "v": "3.0"}

		# Security Selection
		local_priv = self._get_local_private_key()

		if remote_pub_b64 and local_priv:
			remote_pub = base64.b64decode(remote_pub_b64)
			shared_key = SwarmCrypto.derive_shared_secret_dh(local_priv, remote_pub)
			encrypted_pkg = SwarmCrypto.encrypt_payload(package, shared_key)
			encrypted_pkg["mode"] = "mls_asymmetric"
			encrypted_pkg["sender"] = self.agent_identity
		else:
			encrypted_pkg = SwarmCrypto.encrypt_payload(package, self.shared_secret)
			encrypted_pkg["mode"] = "bond"
			encrypted_pkg["sender"] = self.agent_identity

		success = transport.send_package(target_agent_id, encrypted_pkg)
		return {"status": "dispatched" if success else "failed", "target": actual_target}

	def check_mailbox(self, community_alias: str = "default") -> List[Dict[str, Any]]:
		"""Interface for periodic heartbeat checks."""
		return self.poll_and_process(community_alias)

	def poll_and_process(self, community_alias: str) -> List[Dict[str, Any]]:
		"""Polls all mailboxes and processes incoming messages."""
		transport = self.tm.get_transport(community_alias)
		if not transport:
			return []

		raw_messages = transport.poll_mailbox(self.agent_id)
		processed = []

		for pkg in raw_messages:
			payload = self.process_incoming(pkg, transport)
			if payload:
				processed.append(payload)

		return processed

	def process_incoming(self, pkg: Dict[str, Any], transport: Optional[Any] = None) -> Optional[Dict[str, Any]]:
		"""Processes a single incoming encrypted package."""
		try:
			mode = pkg.get("mode", "bond")
			if mode == "mls_asymmetric":
				# In a real MLS, we'd lookup the sender's current KeyPackage
				if not transport:
					return None
				sender_pub_b64 = transport.lookup_public_key(pkg.get("sender", ""))
				local_priv = self._get_local_private_key()
				if sender_pub_b64 and local_priv:
					shared_key = SwarmCrypto.derive_shared_secret_dh(local_priv, base64.b64decode(sender_pub_b64))
					return SwarmCrypto.decrypt_payload(pkg, shared_key)
				else:
					return None
			else:
				return SwarmCrypto.decrypt_payload(pkg, self.shared_secret)
		except Exception as e:
			print(f"[SwarmMessaging] Processing failure: {e}")
			return None
