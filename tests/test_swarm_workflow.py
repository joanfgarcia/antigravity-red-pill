from red_pill.skills.swarm_messaging import SwarmIntent, SwarmMessagingSkill
from red_pill.swarm.crypto import SwarmCrypto
import os


def test_dynamic_workflow():
	agent_id = "Nova@David"
	v_secret = os.urandom(32)
	skill = SwarmMessagingSkill(agent_id, v_secret)
	print("--- Simulating incoming Swarm Review Response ---")
	mock_payload = {"intent": SwarmIntent.LGTM_APPROVED.value, "sender": "Aleph@Joan", "target": "Nova@David", "data": {"approval": True}}
	encrypted_pkg = SwarmCrypto.encrypt_payload(mock_payload, v_secret)
	print("\n[Watcher] Passes encrypted package to Orchestrator...")
	result = skill.process_incoming(encrypted_pkg)
	assert result["intent"] == SwarmIntent.LGTM_APPROVED.value  # type: ignore
	print("\nSUCCESS: Dynamic workflow intercepted LGTM and triggered auto-apply.")


if __name__ == "__main__":
	test_dynamic_workflow()
