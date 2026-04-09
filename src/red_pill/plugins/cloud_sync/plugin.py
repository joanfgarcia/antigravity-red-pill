import logging
import os

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from red_pill import config as cfg
from red_pill.plugins import hookspecs
from red_pill.plugins.base import RedPillPlugin

logger = logging.getLogger(__name__)


def _resolve_credential_path(raw_path: str) -> str:
	"""Resolve credential paths: absolute paths pass through, relative ones
	are anchored to IA_DIR for daemon-safe resolution."""
	if not raw_path:
		return ""
	if os.path.isabs(raw_path):
		return raw_path
	return os.path.join(cfg.IA_DIR, raw_path)


class CloudSyncPlugin(RedPillPlugin):
	plugin_name = "cloud_sync"

	def __init__(self):
		super().__init__()
		self.enabled = self.config.get("enabled", True)
		self.folder_id = self.config.get("folder_id", "")
		self.service_account_file = _resolve_credential_path(self.config.get("service_account_file", ""))
		self.client_secrets_file = _resolve_credential_path(self.config.get("client_secrets_file", ""))
		self.quota_mb = self.config.get("quota_mb", 2048)
		self.reserve_count = self.config.get("reserve_count", 3)
		self.service = None

		# Token path: Sovereign Credential Standard (v6.4.1)
		self.token_file = os.path.expanduser("~/.agent/credentials/drive_token.json")

		if self.enabled and (self.service_account_file or self.client_secrets_file):
			self._authenticate()
		else:
			if self.enabled:
				logger.info("CloudSync enabled but no credentials provided in config.")

	def _emit_pain(self, signal_name: str, detail: str) -> None:
		"""Emit a muted PainSignal to MinionInbox for the Auto-Healer pipeline."""
		try:
			from red_pill.core.inbox import MinionInbox
			inbox = MinionInbox()
			inbox.drop_report(
				event_id=f"signal_{signal_name}",
				source="CloudSyncPlugin",
				status="error",
				content=detail,
			)
			logger.info(f"CloudSync: PainSignal '{signal_name}' emitted to MinionInbox.")
		except Exception as inbox_err:
			logger.error(f"CloudSync: Failed to emit PainSignal: {inbox_err}")

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
							self._emit_pain("cloud_sync_auth_refresh", str(refresh_err))
							creds = None

					if not creds:
						if os.path.exists(self.client_secrets_file):
							flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, scopes)
							creds = flow.run_local_server(port=43303, open_browser=False, success_message="ritual_complete")
							os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
							with open(self.token_file, "w") as token:
								token.write(creds.to_json())

				if creds:
					self.service = build("drive", "v3", credentials=creds)
					logger.info("CloudSync (Google Drive OAuth2) active.")
					return
			except Exception as e:
				logger.error(f"CloudSync OAuth2 Flow failed: {e}")
				self._emit_pain("cloud_sync_auth_flow", str(e))

		if os.path.exists(self.service_account_file):
			try:
				from google.oauth2 import service_account
				creds = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=scopes)
				self.service = build("drive", "v3", credentials=creds)
				logger.info("CloudSync (Service Account) active.")
			except Exception as e:
				logger.error(f"CloudSync Service Account Auth failed: {e}")
				self._emit_pain("cloud_sync_auth_sa", str(e))
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
	def on_soul_created(self, event) -> None:
		"""Uploads the newly created encrypted kit."""
		from red_pill.events import SoulCreatedEvent
		if not isinstance(event, SoulCreatedEvent):
			return

		zip_path = event.zip_path
		if not self.enabled or not self.service:
			return

		# Race condition guard: verify the kit file actually exists on disk
		if not os.path.exists(zip_path):
			logger.error(f"CloudSync: Kit file does not exist: {zip_path}")
			self._emit_pain("cloud_sync_error", f"Kit file missing: {zip_path}")
			return

		file_name = os.path.basename(zip_path)
		file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)

		current_usage = self.get_vault_usage()
		remaining_mb = self.quota_mb - current_usage
		buffer_needed_mb = file_size_mb * self.reserve_count

		if remaining_mb < buffer_needed_mb:
			logger.warning(f"CloudSync Low space! Remaining: {remaining_mb:.1f}MB.")
			self._emit_pain("cloud_sync_low_space", f"Remaining: {remaining_mb:.1f}MB, needed: {buffer_needed_mb:.1f}MB")

		logger.info(f"CloudSync: Uploading {file_name} ({file_size_mb:.1f}MB)...")
		try:
			file_metadata = {"name": file_name}
			if self.folder_id:
				file_metadata["parents"] = [self.folder_id]

			media = MediaFileUpload(zip_path, mimetype="application/octet-stream", resumable=True)
			file = self.service.files().create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
			logger.info(f"CloudSync: Upload successful. File ID: {file.get('id')}")
		except Exception as e:
			logger.error(f"CloudSync Upload failed: {e}")
			self._emit_pain("cloud_sync_error", str(e))
