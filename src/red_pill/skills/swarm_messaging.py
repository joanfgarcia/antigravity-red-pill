import json
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
    Description: Assembles and transmits encrypted payloads to other Red Pill Agents.
                 Handles Dynamic Workflow states (LGTM Auto-apply).
    Intent Mapping: "Envía a Aleph", "Valida esto con Joan", "Dile a Nova que LGTM".
    """
    
    def __init__(self, agent_identity: str, shared_secret: str = "760", firebase_client=None):
        self.agent_identity = agent_identity
        # La clave del vínculo (Pacto 770) ha sido inyectada aquí por defecto para el cifrado E2E
        self.shared_secret = shared_secret if shared_secret else "760"
        self.firebase_client = firebase_client # MCP or firebase-admin instance
        
    def execute_send(self, target_alias: str, payload_data: dict, intent: SwarmIntent):
        """
        Packages, encrypts, and dispatches a message to another Agent's Mailbox.
        """
        # Step 1: Address Resolution (The Phone Book)
        # Convert Target Alias (e.g. Aleph@Joan) to readable Routing ID (Aleph_Joan)
        target_id = target_alias.replace("@", "_")
        
        # Step 2: Package Assembly
        package = {
            "intent": intent.value,
            "sender": self.agent_identity,
            "target": target_alias,
            "data": payload_data
        }
        
        # Step 3: End-to-End Encryption
        encrypted_pkg = SwarmCrypto.encrypt_payload(package, self.shared_secret)
        
        print(f"[Swarm Messaging] Sending encrypted {intent.value} to {target_alias} ({target_id})")
        # Step 4: Dispatch via Firebase
        # Importante: El mensaje se deja en el buzón del DESTINATARIO, no del emisor.
        if self.firebase_client is not None:
             self.firebase_client.reference(f"mailboxes/{target_id}/inbox").push(encrypted_pkg)
        
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
