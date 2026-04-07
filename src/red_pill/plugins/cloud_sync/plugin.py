import logging
import os

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from red_pill.plugins import hookspecs
from red_pill.plugins.base import RedPillPlugin

logger = logging.getLogger(__name__)

class CloudSyncPlugin(RedPillPlugin):
	plugin_name = "cloud_sync"

	def __init__(self):
		super().__init__()
		self.enabled = self.config.get("enabled", True)
		self.folder_id = self.config.get("folder_id", "")
		self.service_account_file = self.config.get("service_account_file", "")
		self.client_secrets_file = self.config.get("client_secrets_file", "")
		self.quota_mb = self.config.get("quota_mb", 2048)
		self.reserve_count = self.config.get("reserve_count", 3)
		self.service = None

		# Token paths within the plugin folder
		ia_dir = os.path.expanduser(os.getenv("IA_DIR", "~/.gemini/antigravity"))
		self.token_file = os.path.join(ia_dir, "plugins", self.plugin_name, "drive_token.json")

		if self.enabled and (self.service_account_file or self.client_secrets_file):
			self._authenticate()
		else:
			if self.enabled:
				logger.info("CloudSync enabled but no credentials provided in config.")

	def _authenticate(self):
		scopes = ["https://www.googleapis.com/auth/drive.file"]

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
							logger.warning(f"OAuth2 refresh failed: {refresh_err}")
							creds = None

					if not creds:
						if os.path.exists(self.client_secrets_file):
							flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, scopes)
							creds = flow.run_local_server(port=43303, open_browser=False, success_message="ritual_complete")
							with open(self.token_file, "w") as token:
								token.write(creds.to_json())

				if creds:
					self.service = build("drive", "v3", credentials=creds)
					logger.info("CloudSync (Google Drive OAuth2) active.")
					return
			except Exception as e:
				logger.error(f"CloudSync OAuth2 Flow failed: {e}")

		if os.path.exists(self.service_account_file):
			try:
				from google.oauth2 import service_account
				creds = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=scopes)
				self.service = build("drive", "v3", credentials=creds)
				logger.info("CloudSync (Service Account) active.")
			except Exception as e:
				logger.error(f"CloudSync Service Account Auth failed: {e}")
				self.enabled = False
		else:
			logger.warning("CloudSync enabled but credentials files missing. Disabled.")
			self.enabled = False

	def get_vault_usage(self) -> float:
		if not self.enabled or not self.service:
			return 0.0
		try:
			query = "trashed = false"
			if self.folder_id:
				query += f" and '{self.folder_id}' in parents"
			results = self.service.files().list(q=query, spaces="drive", fields="files(id, name, size)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
			total_bytes = sum(int(f.get("size", 0)) for f in results.get("files", []))
			return total_bytes / (1024 * 1024)
		except Exception:
			return 0.0

	@hookspecs.hookimpl
	def on_soul_created(self, zip_path: str) -> None:
		"""Uploads the newly created encrypted kit."""
		if not self.enabled or not self.service:
			return

		file_name = os.path.basename(zip_path)
		file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)

		current_usage = self.get_vault_usage()
		remaining_mb = self.quota_mb - current_usage
		buffer_needed_mb = file_size_mb * self.reserve_count

		if remaining_mb < buffer_needed_mb:
			logger.warning(f"CloudSync Low space! Remaining: {remaining_mb:.1f}MB.")

		logger.info(f"CloudSync: Uploading {file_name}...")
		try:
			file_metadata = {"name": file_name}
			if self.folder_id:
				file_metadata["parents"] = [self.folder_id]

			media = MediaFileUpload(zip_path, mimetype="application/octet-stream", resumable=True)
			file = self.service.files().create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
			logger.info(f"CloudSync: Upload successful. File ID: {file.get('id')}")
		except Exception as e:
			# We will emit PainSignal here later
			logger.error(f"CloudSync Upload failed: {e}")
