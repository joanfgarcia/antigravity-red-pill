import os
import tempfile
from unittest.mock import patch

import pytest

from red_pill.utils.vault import SoulCryptographer
from red_pill.utils.vault_crypto import VaultCrypto


@pytest.fixture
def temp_ia_dir():
	"""Creates a temporary IA directory and mocks environment variables."""
	with tempfile.TemporaryDirectory() as tmp_dir:
		with patch.dict(
			os.environ,
			{
				"WORKSPACE_ROOT": tmp_dir,
				"CLOUD_VAULT_ENABLED": "False",  # Disable real API calls
				"CLOUD_VAULT_GPG_PASSPHRASE": "test_passphrase_770",
			},
		):
			yield tmp_dir


def test_vault_mls_encryption_cycle(temp_ia_dir):
	"""Tests that a file can be encrypted and decrypted using MLS."""
	vault = SoulCryptographer()

	# Create a dummy soul kit
	kit_path = os.path.join(temp_ia_dir, "test_kit.tar.gz")
	with open(kit_path, "wb") as f:
		f.write(b"fake soul data 123")

	# 1. Encrypt using MLS (default)
	encrypted_path = vault.encrypt_kit(kit_path)
	assert encrypted_path is not None
	assert encrypted_path.endswith(".mls")
	assert os.path.exists(encrypted_path)

	# 2. Decrypt using the dual-mode decryptor
	decrypted_path = vault.decrypt_kit(encrypted_path)
	assert decrypted_path is not None
	assert not decrypted_path.endswith(".mls")

	with open(decrypted_path, "rb") as f:
		assert f.read() == b"fake soul data 123"


def test_vault_identity_persistence(temp_ia_dir):
	"""Tests that the vault identity is persistent across vault instances."""
	kem1, sig1 = VaultCrypto.get_identity()
	kem2, sig2 = VaultCrypto.get_identity()

	assert kem1.public_bytes() == kem2.public_bytes()
	assert sig1.public_bytes() == sig2.public_bytes()
