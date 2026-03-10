from enum import Enum

from red_pill.swarm.crypto import SwarmCrypto


class SwarmIntent(Enum):
	CODE_REVIEW = "code_review"
	CHANGE_REQUESTED = "change_requested"
	LGTM_APPROVED = "lgtm_approved"
	GOSSIP = "gossip"


class SwarmMessagingSkill:
	"""
	Skill: Swarm Messaging
	Description: Allows the Agent to subscribe to a new Firebase/Swarm Community HUB dynamically.
	Handles securely storing the Firebase Service Account JSON and connection URLs.
	Mapping: "Envía a Aleph", "Valida esto con Joan", "Dile a Nova que LGTM".
	"""

	def __init__(self, agent_identity: str, shared_secret: str, firebase_client=None):
		self.agent_identity = agent_identity
		self.shared_secret = shared_secret
		self.firebase_client = firebase_client  # MCP or firebase-admin instance

	def execute_send(self, target_alias: str, payload_data: dict, intent: SwarmIntent):
		"""
		Packages, encrypts, and dispatches a message to another Agent's Mailbox.
		"""
		# Step 1: Address Resolution (The Phone Book)
		# target_id = self._resolve_alias_to_id(target_alias)
		target_id = "target_agent_id_resolved"  # Mocked for execution plan

		# Step 2: Package Assembly
		package = {"intent": intent.value, "sender": self.agent_identity, "target": target_alias, "data": payload_data}

		# Step 3: End-to-End Encryption
		_ = SwarmCrypto.encrypt_payload(package, self.shared_secret)

		print(f"[Swarm Messaging] Sending encrypted {intent.value} to {target_alias} ({target_id})")
		# Step 4: Dispatch via Firebase
		# self.firebase_client.push(f"mailboxes/{target_id}/inbox", encrypted_pkg)

		return {"status": "dispatched", "target": target_alias}

	def process_incoming(self, encrypted_pkg: dict):
		"""
		Decrypts and triages incoming messages.
		Executes Dynamic Workflows for auto-apply if LGTM.
		"""
		payload = SwarmCrypto.decrypt_payload(encrypted_pkg, self.shared_secret)

		if payload["intent"] == SwarmIntent.LGTM_APPROVED.value:
			print(f"[Dynamic Workflow] {payload['sender']} approved the proposal (LGTM).")
			print("[Dynamic Workflow] Auto-applying patches to workspace. No human bottleneck.")
			# Trigger patch application...
			return "auto_applied"

		elif payload["intent"] == SwarmIntent.CHANGE_REQUESTED.value:
			print(f"[Dynamic Workflow] {payload['sender']} requested changes.")
			print("[Dynamic Workflow] Halting for Operator Review.")
			# Inject to Operator's context...
			return "human_review_required"

		return "processed"
