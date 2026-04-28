from red_pill.swarm.crypto import SwarmCrypto
from red_pill.swarm.mls import SovereignGroup


def test_mls_ratchet_initialization():
	"""Verify SovereignGroup initializes with key_epoch 1 and message_count 0."""
	group = SovereignGroup("test_community")
	assert group.key_epoch == 1
	assert group.message_count == 0


def test_mls_ratchet_rotation():
	"""Verify ratcheting the TreeKEM group key advances epoch and resets counter."""
	group = SovereignGroup("test_community")

	# Simulate 100 messages
	for _ in range(100):
		group.increment_message()

	assert group.should_rotate() is True

	old_key = group.get_group_key()
	new_epoch = group.rotate_key()
	new_key = group.get_group_key()

	assert new_epoch == 2
	assert group.message_count == 0
	assert group.key_epoch == 2
	assert old_key != new_key  # Cryptographic keys must strictly differ


def test_mls_epoch_synchronization():
	"""Verify that an older client can fast-forward to a new epoch detected in a payload header."""
	sender_group = SovereignGroup("test_community")
	receiver_group = SovereignGroup("test_community")

	# Both have the same base roots
	sender_group.root_secret = b"shared_root_seed_1234"
	receiver_group.root_secret = b"shared_root_seed_1234"

	# Sender sends 100 messages and rotates
	for _ in range(101):
		sender_group.increment_message()
		if sender_group.should_rotate():
			sender_group.rotate_key()

	assert sender_group.key_epoch == 2

	# Sender encrypts a new message
	sender_key = sender_group.get_group_key()
	payload = SwarmCrypto.encrypt_payload({"msg": "Hello Future"}, sender_key)

	# Receiver is still at epoch 1. Without syncing, decryption would fail
	# But SwarmMessaging syncs it:
	receiver_group.sync_epoch(sender_group.key_epoch)
	receiver_key = receiver_group.get_group_key()

	assert receiver_key == sender_key

	# Prove decryption works
	decrypted = SwarmCrypto.decrypt_payload(payload, receiver_key)
	assert decrypted["msg"] == "Hello Future"
