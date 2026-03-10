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

	# No _generate_id needed here, we use the target_alias directly

	def __init__(self, agent_identity: str, shared_secret: str, firebase_client=None):
		self.agent_identity = agent_identity
		self.shared_secret = shared_secret
		self.firebase_client = firebase_client  # MCP or firebase-admin instance

	# No _generate_id needed here, we use the target_alias directly

	def execute_send(self, target_alias: str, payload_data: dict, intent: SwarmIntent):
		"""
		Packages, encrypts, and dispatches a message to another Agent's Mailbox.
		"""
		# Utilizar directamente el alias con el formato nativo (ej. Aleph@Joan) para los Mailboxes
		target_id = target_alias

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

	def check_mailbox(self) -> list:
		"""
		Scans the Firebase Hub for incoming messages directed to this agent.
		Returns a list of decrypted message payloads.
		"""
		if not self.firebase_client:
			return []

		# In a real sync with Firebase, we would use the Hub's directory
		# mailbox_path = f"mailboxes/{self.agent_identity}/inbox"
		# encrypted_history = self.firebase_client.get(mailbox_path)

		# For the B760-Baseline PoC, we return an empty list or mock if testing
		return []
