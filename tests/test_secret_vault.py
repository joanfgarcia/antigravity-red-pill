import os
import tempfile
from unittest.mock import patch

import pytest

from red_pill.utils.vault import SecretVault


@pytest.fixture
def temp_ia_dir():
	"""Creates a temporary IA directory and mocks environment variables."""
	with tempfile.TemporaryDirectory() as tmp_dir:
		with patch.dict(
			os.environ,
			{
				"WORKSPACE_ROOT": tmp_dir,
				"CLOUD_VAULT_ENABLED": "False",
			},
		):
			yield tmp_dir


def test_secret_vault_operations(temp_ia_dir):
	"""Test setting, getting, listing and deleting secrets."""
	custom_path = os.path.join(temp_ia_dir, ".test_secrets.mls")
	vault = SecretVault(secrets_path=custom_path)

	# 1. Initially empty
	assert vault.list_secrets() == []
	assert vault.get_secret("nonexistent") is None

	# 2. Set secret
	assert vault.set_secret("db_password", "super_secure_pass") is True
	assert vault.get_secret("db_password") == "super_secure_pass"
	assert vault.list_secrets() == ["db_password"]

	# 3. Update secret
	assert vault.set_secret("db_password", "new_secure_pass") is True
	assert vault.get_secret("db_password") == "new_secure_pass"

	# 4. Set another secret
	assert vault.set_secret("api_key", "xyz123") is True
	assert sorted(vault.list_secrets()) == ["api_key", "db_password"]

	# 5. Delete secret
	assert vault.delete_secret("db_password") is True
	assert vault.get_secret("db_password") is None
	assert vault.list_secrets() == ["api_key"]

	# 6. Delete nonexistent secret
	assert vault.delete_secret("nonexistent") is False
