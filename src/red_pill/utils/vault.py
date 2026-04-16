import logging
import os
import subprocess
from typing import Optional

from pure_mls.group import MLSGroup

from red_pill.utils.vault_crypto import VaultCrypto

logger = logging.getLogger(__name__)

# SEC-001: Vault State Persistence
VAULT_STATE_PATH = os.path.join(os.path.expanduser("~/.config/red_pill"), "vault_group.state")

class SoulCryptographer:
	"""
	Sovereign Vault Cryptography (Refactored in v6.4 -> Core Plugin System).
	Handles ONLY local Pure-MLS / GPG Encryption of Soul Kits.
	Cloud transmissions are now handled by the 'cloud_sync' plugin via the EventBus.
	"""

	def _get_vault_group(self) -> MLSGroup:
		"""Retrieves or initializes the MLS Group for Vault encryption."""
		kem_key, sig_key = VaultCrypto.get_identity()

		if os.path.exists(VAULT_STATE_PATH):
			try:
				with open(VAULT_STATE_PATH, "rb") as f:
					data = f.read()
				group = MLSGroup.from_bytes(data)
				group.my_kem_key = kem_key
				group.my_sig_key = sig_key
				# [v6.6.1] Proactive health check for KeySchedule size mismatch (v3 migration)
				group.encrypt_application_message(b"ping")
				return group
			except Exception as e:
				logger.warning(f"Sovereign Vault state incompatible or corrupt ({e}). Regenerating...")

		logger.info("Initializing new Sovereign Vault Group...")
		group = MLSGroup.create(b"SovereignVaultV1", sig_key, kem_key)
		with open(VAULT_STATE_PATH, "wb") as f:
			f.write(group.to_bytes())
		return group

	def encrypt_kit(self, file_path: str) -> Optional[str]:
		"""Encrypts a Soul Kit. Defaults to MLS."""
		return self._encrypt_kit_mls(file_path)

	def _encrypt_kit_mls(self, file_path: str) -> Optional[str]:
		"""Encrypts a Soul Kit using pure-mls (RFC 9420)."""
		try:
			group = self._get_vault_group()
			with open(file_path, "rb") as f:
				plaintext = f.read()

			ciphertext = group.encrypt_application_message(plaintext)

			encrypted_path = file_path + ".mls"
			with open(encrypted_path, "wb") as f:
				f.write(ciphertext)

			logger.info(f"Soul Kit protected by MLS: {os.path.basename(encrypted_path)}")
			return encrypted_path
		except Exception as e:
			logger.error(f"MLS Encryption failed: {e}")
			return None

	def decrypt_kit(self, encrypted_path: str) -> Optional[str]:
		"""Dual-mode decryption: supports legacy .gpg and new .mls formats."""
		if encrypted_path.endswith(".gpg"):
			return self._decrypt_kit_gpg(encrypted_path)
		elif encrypted_path.endswith(".mls"):
			return self._decrypt_kit_mls(encrypted_path)
		else:
			logger.error(f"Unknown encryption format for {encrypted_path}")
			return None

	def _decrypt_kit_gpg(self, encrypted_path: str) -> Optional[str]:
		"""Legacy GPG Decryption."""
		passphrase = os.getenv("VAULT_GPG_PASSPHRASE", "").strip()
		if not passphrase:
			logger.error("Passphrase required for GPG decryption.")
			return None

		output_path = encrypted_path.replace(".gpg", "")
		try:
			subprocess.run(
				["gpg", "--batch", "--yes", "--passphrase-fd", "0", "--output", output_path, "--decrypt", encrypted_path],
				input=passphrase,
				capture_output=True,
				text=True,
				check=True,
			)
			return output_path
		except Exception as e:
			logger.error(f"GPG Decryption failed: {e}")
			return None

	def _decrypt_kit_mls(self, encrypted_path: str) -> Optional[str]:
		"""MLS Decryption."""
		try:
			group = self._get_vault_group()
			with open(encrypted_path, "rb") as f:
				ciphertext = f.read()

			plaintext = group.decrypt_application_message(ciphertext)

			output_path = encrypted_path.replace(".mls", "")
			with open(output_path, "wb") as f:
				f.write(plaintext)

			return output_path
		except Exception as e:
			logger.error(f"MLS Decryption failed: {e}")
			return None
