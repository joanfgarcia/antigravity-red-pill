import logging
import os
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import red_pill.config as cfg

logger = logging.getLogger(__name__)

class CloudVault:
	"""
	Secure Cloud Storage for Red Pill Soul Kits.
	Supports Google Drive as a 'Digital Haven'.
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
			logger.warning(f"Cloud Vault Service Account file missing: {self.service_account_file}")
			self.enabled = False
			return

		try:
			scopes = ['https://www.googleapis.com/auth/drive.file']
			creds = service_account.Credentials.from_service_account_file(
				self.service_account_file, scopes=scopes
			)
			self.service = build('drive', 'v3', credentials=creds)
			logger.info("Cloud Vault (Google Drive) authenticated successfully.")
		except Exception as e:
			logger.error(f"Cloud Vault authentication failed: {e}")
			self.enabled = False

	def upload_kit(self, file_path: str) -> Optional[str]:
		"""
		Uploads a Soul Kit (tar.gz) to the cloud vault.
		Returns the File ID if successful.
		"""
		if not self.enabled or not self.service:
			return None

		file_name = os.path.basename(file_path)
		logger.info(f"Transmitting Soul Kit to Cloud Haven: {file_name}")

		try:
			file_metadata = {'name': file_name}
			if self.folder_id:
				file_metadata['parents'] = [self.folder_id]

			media = MediaFileUpload(file_path, mimetype='application/gzip', resumable=True)
			
			file = self.service.files().create(
				body=file_metadata,
				media_body=media,
				fields='id'
			).execute()

			file_id = file.get('id')
			logger.info(f"Soul Kit secured in Cloud Vault. File ID: {file_id}")
			return file_id
		except Exception as e:
			logger.error(f"Failed to transmit Soul Kit to Cloud: {e}")
			return None

	def list_backups(self):
		"""Lists available Soul Kits in the vault."""
		if not self.enabled or not self.service:
			return []

		try:
			query = "mimeType = 'application/gzip'"
			if self.folder_id:
				query += f" and '{self.folder_id}' in parents"

			results = self.service.files().list(
				q=query,
				spaces='drive',
				fields='files(id, name, createdTime)',
				orderBy='createdTime desc'
			).execute()
			
			return results.get('files', [])
		except Exception as e:
			logger.error(f"Failed to list cloud backups: {e}")
			return []
