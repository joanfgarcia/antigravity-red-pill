import tempfile
from unittest.mock import patch

import pytest
from pure_mls.keys import KemKey, SignatureKey

from red_pill.swarm.mls_manager import MLSManager


@pytest.fixture
def temp_swarm_dir():
	"""Creates a temporary IA directory for each agent."""
	with tempfile.TemporaryDirectory() as tmp_dir:
		with patch("red_pill.swarm.mls_manager.SWARM_STATE_DIR", tmp_dir):
			yield tmp_dir


def get_mock_identity(seed_bytes: bytes):
	"""Returns a Tuple[KemKey, SignatureKey] from a seed."""
	return KemKey.from_private_bytes(seed_bytes), SignatureKey.from_private_bytes(seed_bytes)


def test_swarm_messaging_flow(temp_swarm_dir):
	"""
	Simulates a complete Swarm MLS flow between two agents.
	1. Agent A (Creator) initializes a community.
	2. Agent B (Joiner) receives a Welcome and joins.
	3. They exchange messages.
	"""

	# --- Setup Agent A ---
	id_a = get_mock_identity(b"agent_a_seed_32_bytes_long_!!!!!")
	with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=id_a):
		manager_a = MLSManager()

	# --- Setup Agent B ---
	id_b = get_mock_identity(b"agent_b_seed_32_bytes_long_!!!!!")
	with patch("red_pill.utils.vault_crypto.VaultCrypto.get_identity", return_value=id_b):
		manager_b = MLSManager()

	# 1. Agent A creates community "test-hive"
	community_alias = "test-hive"
	group_a = manager_a.create_community(community_alias)
	assert group_a.group_id == b"test-hive"

	# 2. Agent A adds Agent B
	kp_b = manager_b.get_key_package()
	group_a, welcome, update = group_a.add_member(kp_b)
	manager_a.groups[community_alias] = group_a  # Update state in manager_a

	# 3. Agent B joins the community
	group_b = manager_b.join_community(community_alias, welcome)
	assert group_b.epoch_id == group_a.epoch_id

	# 4. Agent A encrypts a message for Agent B
	secret_message = b"Red-Pill: The rabbit hole is deep."
	ciphertext = manager_a.encrypt(community_alias, secret_message)

	# 5. Agent B decrypts the message
	decrypted = manager_b.decrypt(community_alias, ciphertext)
	assert decrypted == secret_message

	# 6. Agent B replies
	reply = b"Understood. Moving to STATE-02."
	ciphertext_reply = manager_b.encrypt(community_alias, reply)

	# 7. Agent A decrypts the reply
	decrypted_reply = manager_a.decrypt(community_alias, ciphertext_reply)
	assert decrypted_reply == reply

	print("\n[✅ SWARM MLS SUCCESS] E2E Messaging Verified.")
