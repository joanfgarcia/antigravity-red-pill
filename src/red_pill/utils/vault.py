import logging
import os
from typing import Optional

from pure_mls.group import MLSGroup

from red_pill.core.paths import get_config_dir
from red_pill.utils.vault_crypto import VaultCrypto

logger = logging.getLogger(__name__)

# SEC-001: Vault State Persistence
VAULT_STATE_PATH = os.path.join(get_config_dir(), "vault_group.state")


class SoulCryptographer:
	"""
	Sovereign Vault Cryptography (Refactored in v6.8 -> Pure-MLS).
	Handles local Pure-MLS Encryption/Decryption of Soul Kits.
	Legacy GPG support has been purged for Zero-Bloat sovereignty.
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
		"""MLS Decryption for .mls formats."""
		if not encrypted_path.endswith(".mls"):
			logger.error(f"Unsupported encryption format: {encrypted_path}. GPG legacy was purged.")
			return None

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
