import base64
import os

import pytest

from red_pill.swarm.crypto import SwarmCrypto


def test_generate_x25519_keypair():
	"""Verify X25519 keypair generation produces raw bytes of correct length."""
	priv, pub = SwarmCrypto.generate_x25519_keypair()
	assert isinstance(priv, bytes)
	assert isinstance(pub, bytes)
	assert len(priv) == 32
	assert len(pub) == 32


def test_verify_notary_signature():
	"""Verify Ed25519 digital signature generation and verification."""
	identity = SwarmCrypto.generate_unified_identity()
	seed = identity["seed"]
	public_key = identity["ed25519_pub"]
	data = b"Operation Mjolnir is go."
	signature = SwarmCrypto.sign_notary(private_seed=seed, data=data)
	assert isinstance(signature, bytes)
	is_valid = SwarmCrypto.verify_notary(public_key, data, signature)
	assert is_valid is True
	is_valid_wrong_data = SwarmCrypto.verify_notary(public_key, b"Operation Mjolnir is NO-GO.", signature)
	assert is_valid_wrong_data is False


def test_derive_shared_secret_dh():
	"""Verify Diffie-Hellman shared secret generation."""
	priv1, pub1 = SwarmCrypto.generate_x25519_keypair()
	priv2, pub2 = SwarmCrypto.generate_x25519_keypair()
	secret1 = SwarmCrypto.derive_shared_secret_dh(priv1, pub2)
	secret2 = SwarmCrypto.derive_shared_secret_dh(priv2, pub1)
	assert isinstance(secret1, bytes)
	assert len(secret1) == 32
	assert secret1 == secret2


def test_encrypt_decrypt_payload_bytes_secret():
	"""Verify AES-GCM encryption and decryption of JSON payload with a bytes secret."""
	shared_secret = os.urandom(32)
	payload = {"message": "Hello Swarm", "urgency": "high"}
	encrypted = SwarmCrypto.encrypt_payload(payload, shared_secret)
	assert "v" in encrypted
	assert "nonce" in encrypted
	assert "ciphertext" in encrypted
	decrypted = SwarmCrypto.decrypt_payload(encrypted, shared_secret)
	assert decrypted == payload


def test_encrypt_decrypt_payload_string_secret():
	"""Verify AES-GCM encryption and decryption of JSON payload with a string secret."""
	shared_secret = os.urandom(32)
	payload = {"directive": "Execute Order 66"}
	encrypted = SwarmCrypto.encrypt_payload(payload, shared_secret)
	decrypted = SwarmCrypto.decrypt_payload(encrypted, shared_secret)
	assert decrypted == payload


def test_decrypt_invalid_payload():
	"""Verify decryption fails on corrupted data."""
	shared_secret = os.urandom(16).hex()
	encrypted = SwarmCrypto.encrypt_payload({"data": 1}, shared_secret)
	original_ciphertext_bytes = base64.b64decode(encrypted["ciphertext"])
	corrupted_ciphertext_bytes = original_ciphertext_bytes[:-1] + (b"_" if original_ciphertext_bytes[-1:] != b"_" else b"-")
	encrypted["ciphertext"] = base64.b64encode(corrupted_ciphertext_bytes).decode("utf-8")
	with pytest.raises(ValueError, match="Failed to decrypt Swarm Payload"):
		SwarmCrypto.decrypt_payload(encrypted, shared_secret)
