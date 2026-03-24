import base64
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from red_pill.swarm.mls_bridge import MLSBridge
from red_pill.swarm.transports.manager import TransportManager


class SwarmIntent(Enum):
	CODE_REVIEW = "code_review"
	CHANGE_REQUESTED = "change_requested"
	LGTM_APPROVED = "lgtm_approved"
	GOSSIP = "gossip"
	MLS_WELCOME = "mls_welcome"


class SwarmMessagingSkill:
	"""
	Skill: Swarm Messaging v4.0 (pure-mls, Option B)
	Description: End-to-end encrypted messaging using pure-mls (RFC 9420 / TreeKEM).
	All messages use MLSBridge. Legacy DH/bond modes removed.
	"""

	def __init__(self, agent_identity: str, shared_secret: bytes, transport_manager: Optional[TransportManager] = None):
		self.agent_identity = agent_identity
		self.shared_secret = shared_secret

		import hashlib

		if "@" in agent_identity:
			agent_name, operator_name = agent_identity.split("@", 1)
			raw = f"{agent_name.lower().strip()}:{operator_name.lower().strip()}"
			self.agent_id = f"agt_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
		else:
			self.agent_id = agent_identity

		self.tm = transport_manager or TransportManager()
		self._bridge = MLSBridge(shared_secret)
		self.logger = logging.getLogger(__name__)

	# ------------------------------------------------------------------
	# Send
	# ------------------------------------------------------------------

	def execute_send(self, target_alias: str, payload_data: dict, intent: SwarmIntent, community_alias: str = "default") -> Dict[str, Any]:
		"""
		Sends an MLS-encrypted message to the target agent.
		Flow:
			1. resolve_alias → get (agent_id, full_alias, pub_key, key_package_b64)
			2. If key_package present and no group yet → add_member → push_welcome
			3. Encrypt with MLSBridge → send_package
		"""
		transport = self.tm.get_transport(community_alias)
		if not transport:
			return {"status": "error", "message": f"Transport for '{community_alias}' not found."}

		resolved = transport.resolve_alias(target_alias) if hasattr(transport, "resolve_alias") else None
		if not resolved or len(resolved) < 4:
			return {"status": "error", "message": f"Could not resolve alias '{target_alias}'. Is the target registered?"}

		target_agent_id, actual_target, _pub_key, kp_b64 = resolved

		if "@" not in actual_target:
			return {"status": "error", "message": f"Target '{actual_target}' is not a valid Agent@Operator identifier."}

		# MLS group bootstrap if needed
		if kp_b64:
			if not self._bridge.has_group(community_alias):
				self.logger.info(f"[SwarmMessaging] Bootstrapping MLS group for '{community_alias}' with target '{actual_target}'.")
				try:
					kp_bytes = base64.b64decode(kp_b64)
					welcome_bytes = self._bridge.add_member_and_get_welcome(community_alias, kp_bytes)
					if welcome_bytes and hasattr(transport, "push_welcome"):
						transport.push_welcome(target_agent_id, welcome_bytes)  # type: ignore[union-attr]
						self.logger.info(f"[SwarmMessaging] Welcome pushed to '{actual_target}'.")
				except Exception as e:
					self.logger.error(f"[SwarmMessaging] MLS group bootstrap failed: {e}")
					return {"status": "error", "message": f"MLS group bootstrap failed: {e}"}
		else:
			self.logger.warning(f"[SwarmMessaging] Target '{actual_target}' has no key_package. Cannot use pure-mls.")
			return {"status": "error", "message": f"Target '{actual_target}' is not MLS B1 capable (no key_package in registry)."}

		# Encrypt
		plaintext = json.dumps(
			{"intent": intent.value, "sender": self.agent_identity, "target": actual_target, "data": payload_data, "v": "4.0"}
		).encode("utf-8")
		ciphertext = self._bridge.encrypt(community_alias, plaintext)
		if not ciphertext:
			return {"status": "error", "message": "MLS encryption failed."}

		package = {
			"mode": "pure_mls",
			"sender": self.agent_id,
			"community": community_alias,
			"ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
		}

		success = transport.send_package(target_agent_id, package)
		return {"status": "dispatched" if success else "failed", "target": actual_target}

	# ------------------------------------------------------------------
	# Receive
	# ------------------------------------------------------------------

	def check_mailbox(self, community_alias: str = "default") -> List[Dict[str, Any]]:
		"""Interface for periodic heartbeat checks."""
		return self.poll_and_process(community_alias)

	def poll_and_process(self, community_alias: str) -> List[Dict[str, Any]]:
		"""Polls the mailbox, processes pending Welcomes, then decrypts messages."""
		transport = self.tm.get_transport(community_alias)
		if not transport:
			return []

		# Step 1: Process any pending Welcome (join the group if invited)
		if hasattr(transport, "pop_welcome"):
			welcome_bytes = transport.pop_welcome(self.agent_id)  # type: ignore[union-attr]
			if welcome_bytes:
				self.logger.info(f"[SwarmMessaging] Welcome received for '{community_alias}'. Joining group.")
				self._bridge.process_welcome(community_alias, welcome_bytes)

		# Step 2: Read and decrypt messages
		raw_messages = transport.poll_mailbox(self.agent_id)
		processed = []
		for pkg in raw_messages:
			payload = self.process_incoming(pkg, community_alias)
			if payload:
				processed.append(payload)

		return processed

	def process_incoming(self, pkg: Dict[str, Any], community_alias: str = "default") -> Optional[Dict[str, Any]]:
		"""Decrypts a single incoming MLS package."""
		try:
			mode = pkg.get("mode", "unknown")
			if mode == "pure_mls":
				ciphertext = base64.b64decode(pkg["ciphertext"])
				plaintext = self._bridge.decrypt(community_alias, ciphertext)
				if not plaintext:
					self.logger.error("[SwarmMessaging] MLS decryption returned None.")
					return None
				return json.loads(plaintext.decode("utf-8"))
			else:
				self.logger.warning(f"[SwarmMessaging] Unknown mode '{mode}'. Dropping message.")
				return None
		except Exception as e:
			self.logger.error(f"[SwarmMessaging] process_incoming failed: {e}")
			return None
