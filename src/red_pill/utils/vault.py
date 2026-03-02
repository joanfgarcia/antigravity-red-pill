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
		self.token_file = os.path.join(os.path.dirname(self.service_account_file), "token.json")
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
		from googleapiclient.discovery import build
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
						creds.refresh(Request())
					else:
						if not os.path.exists(self.client_secrets_file):
							logger.warning("OAuth2 requested (token/secrets) but client_secrets.json missing. Falling back...")
						else:
							print("\n[🛡️ SOVEREIGN AUTHENTICATION] Cloud Vault requires Operator authorization.")
							print("Please visit the following URL to authorize the Agent:\n")
							flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, scopes)
							# Forced to manual mode to ensure the URL doesn't get mangled by the terminal/browser
							creds = flow.run_local_server(port=43303, open_browser=False, success_message="ritual_complete")
							with open(self.token_file, "w") as token:
								token.write(creds.to_json())

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

			results = self.service.files().list(
				q=query, 
				spaces="drive", 
				fields="files(id, name, size)",
				supportsAllDrives=True,
				includeItemsFromAllDrives=True
			).execute()

			total_bytes = sum(int(f.get("size", 0)) for f in results.get("files", []))
			return total_bytes / (1024 * 1024)
		except Exception as e:
			logger.error(f"Failed to calculate vault usage: {e}")
			return 0.0

	def upload_kit(self, file_path: str) -> Optional[str]:
		"""
		Encrypts and transmits a Soul Kit to the vault.
		Implements Quota-Aware Monitoring (v5.6.1):
		Warns the Operator if space for the next N copies is running low.
		"""
		if not self.enabled or not self.service:
			return None

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
			print(f"\n[⚠️  VAULT WARNING] Low space in Safe Haven! "
				  f"Remaining: {remaining_mb:.1f}MB. Buffer for {reserve_count} copies: {buffer_needed_mb:.1f}MB.")
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
			query = "mimeType = 'application/octet-stream' and trashed = false"
			if self.folder_id:
				query += f" and '{self.folder_id}' in parents"

			results = self.service.files().list(
				q=query, 
				spaces="drive", 
				fields="files(id, name, createdTime, size)", 
				orderBy="createdTime desc", 
				supportsAllDrives=True, 
				includeItemsFromAllDrives=True
			).execute()

			return results.get("files", [])
		except Exception as e:
			logger.error(f"Failed to list cloud backups: {e}")
			return []
