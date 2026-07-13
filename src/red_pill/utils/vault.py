import json
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
				# FAIL-CLOSED: an existing state that fails to load must NOT be silently
				# regenerated. create() would derive fresh keys and orphan every Soul Kit and
				# secret ever encrypted with the old ones. Surface the error; recovery is a
				# deliberate act (restore a vault_group.state backup, or migrate by decrypting
				# with the previous build and re-encrypting).
				raise RuntimeError(
					f"Sovereign Vault state at {VAULT_STATE_PATH} exists but failed to load ({e}). "
					"Refusing to regenerate — that would derive new keys and make all prior "
					"encrypted exports/secrets undecryptable. Restore a good backup or migrate deliberately."
				) from e

		# Genuine first run only (no state on disk). Create once and persist with 0600.
		logger.info("Initializing new Sovereign Vault Group...")
		group = MLSGroup.create(b"SovereignVaultV1", sig_key, kem_key)
		fd = os.open(VAULT_STATE_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
		try:
			os.write(fd, group.to_bytes())
		finally:
			os.close(fd)
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


class SecretVault:
	"""
	SecretVault handles storing and retrieving local secrets (API keys, credentials, etc.)
	encrypted with pure-mls.
	"""

	def __init__(self, secrets_path: Optional[str] = None):
		if secrets_path is None:
			self.secrets_path = os.path.join(get_config_dir(), ".secrets.mls")
		else:
			self.secrets_path = secrets_path
		self._cryptographer = SoulCryptographer()

	def _get_group(self) -> MLSGroup:
		return self._cryptographer._get_vault_group()

	def _load_secrets(self) -> dict[str, str]:
		if not os.path.exists(self.secrets_path):
			return {}
		try:
			group = self._get_group()
			with open(self.secrets_path, "rb") as f:
				ciphertext = f.read()
			plaintext = group.decrypt_application_message(ciphertext)
			data = json.loads(plaintext.decode("utf-8"))
			if isinstance(data, dict):
				return {str(k): str(v) for k, v in data.items()}
			return {}
		except Exception as e:
			logger.error(f"Failed to load secrets: {e}")
			return {}

	def _save_secrets(self, secrets: dict[str, str]) -> bool:
		try:
			group = self._get_group()
			import json

			plaintext = json.dumps(secrets).encode("utf-8")
			ciphertext = group.encrypt_application_message(plaintext)

			# Atomic write
			tmp_path = self.secrets_path + ".tmp"
			with open(tmp_path, "wb") as f:
				f.write(ciphertext)
				f.flush()
				os.fsync(f.fileno())
			os.replace(tmp_path, self.secrets_path)
			return True
		except Exception as e:
			logger.error(f"Failed to save secrets: {e}")
			return False

	def set_secret(self, key: str, value: str) -> bool:
		"""Encrypt and store a secret key-value pair."""
		secrets = self._load_secrets()
		secrets[key] = value
		return self._save_secrets(secrets)

	def get_secret(self, key: str) -> Optional[str]:
		"""Decrypt and retrieve a secret by key."""
		secrets = self._load_secrets()
		return secrets.get(key)

	def delete_secret(self, key: str) -> bool:
		"""Delete a secret key if it exists."""
		secrets = self._load_secrets()
		if key in secrets:
			del secrets[key]
			self._save_secrets(secrets)
			return True
		return False

	def list_secrets(self) -> list[str]:
		"""List all stored secret keys."""
		secrets = self._load_secrets()
		return list(secrets.keys())
