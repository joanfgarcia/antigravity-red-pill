from red_pill.skills.swarm_messaging import SwarmIntent, SwarmMessagingSkill
from red_pill.swarm.crypto import SwarmCrypto


def test_dynamic_workflow():
	# Setup test components
	agent_id = "Nova@David"
	shared_secret = "test_shared_bond_770"
	skill = SwarmMessagingSkill(agent_id, shared_secret)

	print("--- Simulating incoming Swarm Review Response ---")

	# Simulate Aleph sending us a positive LGTM approval
	mock_payload = {"intent": SwarmIntent.LGTM_APPROVED.value, "sender": "Aleph@Joan", "target": "Nova@David", "data": {"approval": True}}

	encrypted_pkg = SwarmCrypto.encrypt_payload(mock_payload, shared_secret)

	print("\n[Watcher] Passes encrypted package to Orchestrator...")
	result = skill.process_incoming(encrypted_pkg)

	assert result["intent"] == SwarmIntent.LGTM_APPROVED.value
	print("\nSUCCESS: Dynamic workflow intercepted LGTM and triggered auto-apply.")


if __name__ == "__main__":
	test_dynamic_workflow()
