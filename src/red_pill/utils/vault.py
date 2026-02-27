import logging
import os
import subprocess
from typing import Any, Dict, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import red_pill.config as cfg

logger = logging.getLogger(__name__)


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
		self.service: Optional[Any] = None

		if self.enabled:
			self._authenticate()

	def _authenticate(self):
		"""Authenticates with Google Drive using a Service Account."""
		if not os.path.exists(self.service_account_file):
			# SEC-F05: Redact the full path to avoid leaking fs structure in logs
			logger.warning("Cloud Vault Service Account file missing (path redacted). Vault disabled.")
			self.enabled = False
			return

		try:
			scopes = ["https://www.googleapis.com/auth/drive.file"]
			creds = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=scopes)
			self.service = build("drive", "v3", credentials=creds)
			logger.info("Cloud Vault (Google Drive) authenticated successfully.")
		except Exception as e:
			logger.error(f"Cloud Vault authentication failed: {e}")
			self.enabled = False

	def _encrypt_kit(self, file_path: str) -> Optional[str]:
		"""
		SEC-F02: Encrypt a Soul Kit using GPG symmetric AES-256 encryption.
		Returns the path to the encrypted file, or None if encryption fails.
		The caller is responsible for cleaning up the returned temp file.
		"""
		passphrase = os.getenv("CLOUD_VAULT_GPG_PASSPHRASE", "").strip()
		if not passphrase:
			logger.error(
				"SEC-F02: CLOUD_VAULT_GPG_PASSPHRASE is not set. "
				"Soul Kit upload aborted — plaintext transmission is not permitted. "
				"Set CLOUD_VAULT_GPG_PASSPHRASE in your .env to enable Cloud Vault uploads."
			)
			return None

		encrypted_path = file_path + ".gpg"
		try:
			subprocess.run(
				[
					"gpg",
					"--batch",
					"--yes",
					"--symmetric",
					"--cipher-algo",
					"AES256",
					"--passphrase",
					passphrase,
					"--output",
					encrypted_path,
					file_path,
				],
				capture_output=True,
				text=True,
				check=True,
			)
			logger.info(f"Soul Kit encrypted (AES-256): {os.path.basename(encrypted_path)}")
			return encrypted_path
		except FileNotFoundError:
			logger.error("SEC-F02: gpg binary not found. Install gnupg to enable Cloud Vault uploads.")
			return None
		except subprocess.CalledProcessError as e:
			logger.error(f"SEC-F02: GPG encryption failed: {e.stderr}")
			return None

	def upload_kit(self, file_path: str) -> Optional[str]:
		"""
		Encrypts and uploads a Soul Kit (tar.gz → .gpg) to the cloud vault.
		Returns the File ID if successful.
		SEC-F02: Raw (plaintext) upload is prohibited — kit is always encrypted first.
		"""
		if not self.enabled or not self.service:
			return None

		encrypted_path = self._encrypt_kit(file_path)
		if not encrypted_path:
			return None

		file_name = os.path.basename(encrypted_path)
		logger.info(f"Transmitting encrypted Soul Kit to Cloud Haven: {file_name}")

		try:
			file_metadata: Dict[str, Any] = {"name": file_name}
			if self.folder_id:
				file_metadata["parents"] = [self.folder_id]

			media = MediaFileUpload(encrypted_path, mimetype="application/octet-stream", resumable=True)
			file = self.service.files().create(body=file_metadata, media_body=media, fields="id").execute()

			file_id = str(file.get("id"))
			logger.info(f"Encrypted Soul Kit secured in Cloud Vault. File ID: {file_id}")
			return file_id
		except Exception as e:
			logger.error(f"Failed to transmit encrypted Soul Kit to Cloud: {e}")
			return None
		finally:
			# Always clean up the temporary encrypted file
			if os.path.exists(encrypted_path):
				try:
					os.remove(encrypted_path)
				except OSError:
					pass

	def list_backups(self):
		"""Lists available Soul Kits in the vault."""
		if not self.enabled or not self.service:
			return []

		try:
			query = "mimeType = 'application/octet-stream'"
			if self.folder_id:
				query += f" and '{self.folder_id}' in parents"

			results = self.service.files().list(q=query, spaces="drive", fields="files(id, name, createdTime)", orderBy="createdTime desc").execute()

			return results.get("files", [])
		except Exception as e:
			logger.error(f"Failed to list cloud backups: {e}")
			return []
