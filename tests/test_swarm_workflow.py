"""
test_swarm_workflow.py — Updated for SwarmMessagingSkill v4.0 (pure-mls)
"""

import os
from unittest.mock import MagicMock, patch


def _mock_identity(seed: bytes):
	from pure_mls.keys import KemKey, SignatureKey

	seed = seed.ljust(32, b"\x00")[:32]
	return KemKey.from_private_bytes(seed), SignatureKey.from_private_bytes(seed)


def test_dynamic_workflow():
	"""
	Simulates an incoming pure-mls package being processed by SwarmMessagingSkill.
	"""
	import base64
	import json

	from red_pill.skills.swarm_messaging import SwarmIntent, SwarmMessagingSkill
	from red_pill.swarm.mls_bridge import MLSBridge

	secret = os.urandom(32)
	seed_a = b"aleth_seed_workflow_test______"
	seed_b = b"nova__seed_workflow_test______"

	# Build two bridges
	with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(seed_a)):
		bridge_a = MLSBridge(secret)
	with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(seed_b)):
		bridge_b = MLSBridge(secret)

	# A adds B → Welcome
	kp_b, _ = bridge_b.get_my_key_package()
	welcome = bridge_a.add_member_and_get_welcome("test", kp_b)
	bridge_b.process_welcome("test", welcome)

	# B encrypts a LGTM payload
	payload = {"intent": SwarmIntent.LGTM_APPROVED.value, "sender": "Aleph@Joan", "target": "Nova@David", "data": {"approval": True}, "v": "4.0"}
	ciphertext = bridge_b.encrypt("test", json.dumps(payload).encode())
	pkg = {"mode": "pure_mls", "ciphertext": base64.b64encode(ciphertext).decode(), "sender": "agt_b"}

	# A receives and decrypts
	mock_tm = MagicMock()
	with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=_mock_identity(seed_a)):
		skill = SwarmMessagingSkill("Aleph@Joan", secret, transport_manager=mock_tm)
	skill._bridge = bridge_a

	result = skill.process_incoming(pkg, "test")
	assert result is not None
	assert result["intent"] == SwarmIntent.LGTM_APPROVED.value
	print("\nSUCCESS: Dynamic workflow intercepted LGTM via pure-mls v4.0.")


if __name__ == "__main__":
	test_dynamic_workflow()
