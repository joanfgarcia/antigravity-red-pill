import os
from unittest.mock import MagicMock, patch

from red_pill.utils.vault import CloudVault


def test_encrypt_kit_hardened(tmp_path):
	"""ACT-P2-01 & ACT-P3-02: Verify GPG encryption uses the hardened S2K parameters."""
	os.environ["CLOUD_VAULT_GPG_PASSPHRASE"] = "test_passphrase_123"

	dummy_tar = tmp_path / "dummy_backup.tar.gz"
	dummy_tar.write_text("dummy soul data")

	vault = CloudVault()

	with patch("subprocess.run") as mock_run:
		mock_result = MagicMock()
		mock_result.returncode = 0
		mock_run.return_value = mock_result

		output = vault._encrypt_kit(str(dummy_tar))

		assert mock_run.call_count == 1
		cmd_args = mock_run.call_args[0][0]

		assert "gpg" in cmd_args
		assert "--s2k-digest-algo" in cmd_args
		assert "SHA512" in cmd_args
		assert "--s2k-count" in cmd_args
		assert "65011712" in cmd_args

		assert output == str(dummy_tar) + ".gpg"


def test_encrypt_kit_no_passphrase(tmp_path):
	"""Verify upload aborts if no passphrase is provided."""
	if "CLOUD_VAULT_GPG_PASSPHRASE" in os.environ:
		del os.environ["CLOUD_VAULT_GPG_PASSPHRASE"]

	dummy_tar = tmp_path / "dummy_backup.tar.gz"
	dummy_tar.write_text("dummy")

	vault = CloudVault()
	output = vault._encrypt_kit(str(dummy_tar))
	assert output is None
