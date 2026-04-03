import logging
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pure_mls.group import MLSGroup

import red_pill.config as cfg
from red_pill.utils.vault_crypto import VaultCrypto

logger = logging.getLogger(__name__)

# SEC-001: Vault State Persistence
VAULT_STATE_PATH = os.path.join(os.path.expanduser("~/.config/red_pill"), "vault_group.state")

# TODO(post-pure-mls-upgrade): Separate MLS group states by purpose — VAULT-STATE-SPLIT
#
# Currently vault_group.state is shared between:
#   1. LEAN_SOUL_KIT encryption (.tar.gz.mls) — solo-member, epoch-0, never rotates
#   2. Future swarm messaging — multi-member, epoch advances on each commit
#
# Problem: sharing a single MLSGroup state across both use cases couples their
# lifecycles. A swarm key rotation (add_member/process_update) advances the epoch
# and wipes the SecretTree, which breaks decryption of old LEAN_SOUL_KIT ciphertexts
# same group object reuse causes cross-use-case state corruption.
#
# Proposed implementation (after pure-mls ≥ 3.0.0.9 is deployed to red-pill):
#   VAULT_KIT_STATE_PATH   = ~/.config/red_pill/vault_kit.state
#       Purpose: LEAN_SOUL_KIT encryption only. Solo-member. Never rotates.
#       Lifecycle: created once, never advanced. Stable forever.
#   VAULT_SWARM_STATE_PATH = ~/.config/red_pill/vault_swarm.state
#       Purpose: Swarm inter-agent messaging. Multi-member. Rotates per epoch.
#       Lifecycle: advances with each add_member/process_update in MLS swarm.
#
# Compatibility invariant: vault_group.state bytes serialize COMPUTED secrets,
# not derivation formulas. If the file exists and is NOT deleted, it is fully
# compatible across pure-mls versions. Only NEW group creation (MLSGroup.create)
# is affected by changes to genesis derivation (P0-C fix).
#
# Migration path: rename existing vault_group.state → vault_kit.state on first boot
# after the split, so existing LEAN_SOUL_KIT backups remain decryptable.
# See: ARCHITECTURE.md §Vault State Management


class CloudVault:
	"""
	Secure Cloud Storage for Red Pill Soul Kits.
	Supports Google Drive as a 'Digital Haven'.

	SEC-F02: All Soul Kit uploads are GPG-encrypted (AES-256) before transmission.
	Set CLOUD_VAULT_GPG_PASSPHRASE in your .env to enable. Uploads will be
	rejected if the passphrase is not configured (fail-secure posture).
	"""

	def __init__(self):
		self.enabled = cfg.CLOUD_VAULT_ENABLED
		self.folder_id = cfg.CLOUD_VAULT_FOLDER_ID
		self.service_account_file = cfg.CLOUD_SERVICE_ACCOUNT_FILE

		# SEC-F02b: separate token from service account directory
		creds_dir = os.path.join(os.getenv("HOME", "/tmp"), ".agent", "credentials")
		os.makedirs(creds_dir, exist_ok=True)
		self.token_file = os.path.join(creds_dir, "drive_token.json")

		# Zero-touch migration: Move old token if existing to avoid requiring operators to re-authenticate
		legacy_token = os.path.join(os.path.dirname(self.service_account_file), "token.json")
		if os.path.exists(legacy_token) and not os.path.exists(self.token_file):
			try:
				shutil.move(legacy_token, self.token_file)
				logger.info(f"SEC-F02b: Migrated legacy token.json to {self.token_file}")
			except Exception as e:
				logger.warning(f"Failed to migrate legacy token.json: {e}")

		self.client_secrets_file = os.path.join(os.path.dirname(self.service_account_file), "client_secrets.json")
		self.service: Optional[Any] = None

		if self.enabled:
			self._authenticate()

	def _authenticate(self):
		"""
		Hybrid Authenticator (v5.6.1):
		1. Try OAuth2 (Personal/token mode) if client_secrets.json exists.
		2. Fallback to Service Account if JSON found.
		"""

		# SEC Note: Scopes are strictly 'drive.file' to limit the Agent's reach to its own files.
		scopes = ["https://www.googleapis.com/auth/drive.file"]

		# --- METHOD A: OAuth2 (Personal / Act-as-Operator) ---
		if os.path.exists(self.client_secrets_file) or os.path.exists(self.token_file):
			try:
				from google.auth.transport.requests import Request
				from google.oauth2.credentials import Credentials
				from google_auth_oauthlib.flow import InstalledAppFlow

				creds = None
				if os.path.exists(self.token_file):
					creds = Credentials.from_authorized_user_file(self.token_file, scopes)

				if not creds or not creds.valid:
					if creds and creds.expired and creds.refresh_token:
						try:
							creds.refresh(Request())
						except Exception as refresh_err:
							logger.warning(f"OAuth2 refresh failed ({refresh_err}). Re-triggering ritual...")
							creds = None  # Force ritual

					if not creds:
						if not os.path.exists(self.client_secrets_file):
							logger.warning("OAuth2 requested (token/secrets) but client_secrets.json missing. Falling back...")
						else:
							print("\n[🛡️ SOVEREIGN AUTHENTICATION] Cloud Vault requires Operator authorization.")
							print("Please visit the following URL to authorize the Agent:\n")
							flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, scopes)
							creds = flow.run_local_server(port=43303, open_browser=False, success_message="ritual_complete")
							with open(self.token_file, "w") as token:
								token.write(creds.to_json())

				if creds:
					self.service = build("drive", "v3", credentials=creds)
					logger.info("Cloud Vault (Google Drive OAuth2) active.")
					return
			except Exception as e:
				logger.error(f"OAuth2 Flow failed: {e}")

		# --- METHOD B: Service Account (Enterprise/Shared Drive) ---
		if os.path.exists(self.service_account_file):
			try:
				from google.oauth2 import service_account

				creds = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=scopes)
				self.service = build("drive", "v3", credentials=creds)
				logger.info("Cloud Vault (Service Account) active.")
			except Exception as e:
				logger.error(f"Service Account Auth failed: {e}")
				self.enabled = False
		else:
			logger.warning("Cloud Vault enabled but no valid credentials found (client_secrets.json or service_account.json). Vault disabled.")
			self.enabled = False

	def _get_vault_group(self) -> MLSGroup:
		"""
		Retrieves or initializes the MLS Group for Vault encryption.

		IMPORTANT — pure-mls version compatibility:
		The vault_group.state file stores serialized epoch secrets (pre-computed bytes).
		As long as this file is NOT deleted, decryption of existing .mls kits works
		across all pure-mls versions. Only MLSGroup.create() is affected by genesis
		derivation changes — and that only runs when the state file is absent.

		NEVER delete vault_group.state without first decrypting all .mls backups,
		or they will become permanently inaccessible.

		See module-level VAULT-STATE-SPLIT TODO for the planned separation of this
		state into vault_kit.state (LEAN_SOUL_KIT) and vault_swarm.state (messaging).
		"""
		kem_key, sig_key = VaultCrypto.get_identity()

		if os.path.exists(VAULT_STATE_PATH):
			with open(VAULT_STATE_PATH, "rb") as f:
				data = f.read()
			group = MLSGroup.from_bytes(data)
			# Ensure keys are reassigned if they were not serialized (though to_bytes does include them)
			group.my_kem_key = kem_key
			group.my_sig_key = sig_key
		else:
			# Initialize a solo group for the vault
			logger.info("Initializing new Sovereign Vault Group...")
			group = MLSGroup.create(b"SovereignVaultV1", sig_key, kem_key)
			with open(VAULT_STATE_PATH, "wb") as f:
				f.write(group.to_bytes())
		return group

	def _encrypt_kit_mls(self, file_path: str) -> Optional[str]:
		"""
		Encrypts a Soul Kit using pure-mls (RFC 9420).
		Returns path to .mls file.
		"""
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

	def _decrypt_kit(self, encrypted_path: str) -> Optional[str]:
		"""
		Dual-mode decryption: supports legacy .gpg and new .mls formats.
		Returns path to decrypted file.
		"""
		if encrypted_path.endswith(".gpg"):
			return self._decrypt_kit_gpg(encrypted_path)
		elif encrypted_path.endswith(".mls"):
			return self._decrypt_kit_mls(encrypted_path)
		else:
			logger.error(f"Unknown encryption format for {encrypted_path}")
			return None

	def _decrypt_kit_gpg(self, encrypted_path: str) -> Optional[str]:
		"""Legacy GPG Decryption."""
		passphrase = os.getenv("CLOUD_VAULT_GPG_PASSPHRASE", "").strip()
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

	def _encrypt_kit(self, file_path: str) -> Optional[str]:
		"""
		SEC-F02: Encrypts a Soul Kit. Defaults to MLS in v6.1.
		"""
		return self._encrypt_kit_mls(file_path)

	def get_vault_usage(self) -> float:
		"""
		Calculates the total size (MB) of files currently in the folder.
		"""
		if not self.enabled or not self.service:
			return 0.0

		try:
			query = "trashed = false"
			if self.folder_id:
				query += f" and '{self.folder_id}' in parents"

			results = (
				self.service.files()
				.list(q=query, spaces="drive", fields="files(id, name, size)", supportsAllDrives=True, includeItemsFromAllDrives=True)
				.execute()
			)

			total_bytes = sum(int(f.get("size", 0)) for f in results.get("files", []))
			return total_bytes / (1024 * 1024)
		except Exception as e:
			logger.error(f"Failed to calculate vault usage: {e}")
			return 0.0

	def upload_kit(self, file_path: str) -> Optional[str]:
		"""
		Encrypts (if needed) and transmits a Soul Kit to the vault.
		Implements Quota-Aware Monitoring (v5.6.1).
		"""
		if not self.enabled or not self.service:
			return None

		was_already_encrypted = file_path.endswith(".gpg") or file_path.endswith(".mls")
		encrypted_path: Optional[str] = None

		if was_already_encrypted:
			encrypted_path = file_path
			logger.info("Soul Kit already encrypted. Skipping redundant AES-256 layer.")
		else:
			encrypted_path = self._encrypt_kit(file_path)

		if not encrypted_path:
			return None

		file_name = os.path.basename(encrypted_path)
		file_size_mb = os.path.getsize(encrypted_path) / (1024 * 1024)

		# Quota Check (Lean Buffer Manager)
		current_usage = self.get_vault_usage()
		quota_mb = cfg.CLOUD_VAULT_QUOTA_MB
		reserve_count = cfg.CLOUD_VAULT_RESERVE_COUNT
		remaining_mb = quota_mb - current_usage
		buffer_needed_mb = file_size_mb * reserve_count

		logger.info(f"Vault Status: {current_usage:.1f}/{quota_mb}MB used. Remaining: {remaining_mb:.1f}MB.")

		if remaining_mb < buffer_needed_mb:
			print(
				f"\n[⚠️  VAULT WARNING] Low space in Safe Haven! "
				f"Remaining: {remaining_mb:.1f}MB. Buffer for {reserve_count} copies: {buffer_needed_mb:.1f}MB."
			)
			print("Recommendation: Move older kits or increase CLOUD_VAULT_QUOTA_MB in .env.\n")

		logger.info(f"Transmitting encrypted Soul Kit to Cloud Haven: {file_name}")

		try:
			file_metadata: Dict[str, Any] = {"name": file_name}
			if self.folder_id:
				file_metadata["parents"] = [self.folder_id]

			media = MediaFileUpload(encrypted_path, mimetype="application/octet-stream", resumable=True)
			file = self.service.files().create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True).execute()

			file_id = str(file.get("id"))
			logger.info(f"Encrypted Soul Kit secured in Cloud Vault. File ID: {file_id}")
			return file_id
		except Exception as e:
			if "storageQuotaExceeded" in str(e):
				print("\n[❌ CLOUD ERROR] storageQuotaExceeded")
				print("The Service Account has 0 quota. To fix this, you MUST use a 'Unidad Compartida' (Shared Drive).")
				print("A regular folder in 'Mi Unidad' (Shared Folder) will NOT work for uploads from a Service Account.\n")
			logger.error(f"Failed to transmit encrypted Soul Kit to Cloud: {e}")
			return None
		finally:
			# Only cleanup if WE created the encrypted file.
			# If it was already encrypted (local persistence), keep it.
			if encrypted_path and not was_already_encrypted and os.path.exists(encrypted_path):
				try:
					os.remove(encrypted_path)
				except OSError:
					pass

	def list_backups(self):
		"""Lists available Soul Kits in the vault."""
		if not self.enabled or not self.service:
			return []

		try:
			query = "mimeType = 'application/octet-stream' and trashed = false"
			if self.folder_id:
				query += f" and '{self.folder_id}' in parents"

			results = (
				self.service.files()
				.list(
					q=query,
					spaces="drive",
					fields="files(id, name, createdTime, size)",
					orderBy="createdTime desc",
					supportsAllDrives=True,
					includeItemsFromAllDrives=True,
				)
				.execute()
			)

			return results.get("files", [])
		except Exception as e:
			logger.error(f"Failed to list cloud backups: {e}")
			return []
