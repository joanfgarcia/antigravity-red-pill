import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from red_pill import config as cfg
from red_pill.core.plugin_engine import PluginScope, SovereignPlugin

logger = logging.getLogger(__name__)


def _resolve_credential_path(raw_path: str) -> str:
	"""Resolve credential paths: absolute paths pass through, relative ones
	are anchored to IA_DIR for daemon-safe resolution."""
	if not raw_path:
		return ""
	if os.path.isabs(raw_path):
		return raw_path
	return os.path.join(cfg.IA_DIR, raw_path)


class CloudSyncPlugin(SovereignPlugin):
	def __init__(self, name: str = "cloud_sync", version: str = "1.0", directory: Path = None):
		super().__init__(name, version, directory)
		self.enabled = self.config.get("enabled", True)
		self.folder_id = self.config.get("folder_id", "")
		self.service_account_file = _resolve_credential_path(self.config.get("service_account_file", ""))
		self.client_secrets_file = _resolve_credential_path(self.config.get("client_secrets_file", ""))
		self.quota_mb = self.config.get("quota_mb", 2048)
		self.reserve_count = self.config.get("reserve_count", 3)
		self.service = None

	@property
	def scopes(self) -> List[PluginScope]:
		return [PluginScope.SYSTEM_EVENT]

	@property
	def requested_permissions(self) -> List[str]:
		return ["fs:read:backup", "net:outbound:gdrive", "qdrant:write:minion_inbox"]

	async def init(self) -> None:
		# Token path: Sovereign Credential Standard (v6.4.1)
		self.token_file = os.path.join(cfg.IA_DIR, "plugins", self.name, "token.json")

		if self.enabled and (self.service_account_file or self.client_secrets_file):
			self._authenticate()
		else:
			if self.enabled:
				logger.info("CloudSync enabled but no credentials provided in config.")

	async def activate(self) -> None:
		pass

	async def deactivate(self) -> None:
		pass

	async def uninstall(self, purge: bool = False) -> None:
		pass

	async def export_state(self) -> Dict[str, Any]:
		return {}

	async def hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:
		if scope == PluginScope.SYSTEM_EVENT and payload.get("action") == "soul_created":
			self._on_soul_created(payload.get("zip_path"))
		return payload

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

		# JERARQUÍA SOBERANA: 1. Token (Sesión Activa) -> 2. Service Account (Empresa) -> 3. Interactive (Secrets)

		# 1. INTENTO: OAuth2 con Token existente (Recuérdame)
		if os.path.exists(self.token_file):
			try:
				from google.auth.transport.requests import Request
				from google.oauth2.credentials import Credentials

				creds = Credentials.from_authorized_user_file(self.token_file, scopes)

				if creds and creds.expired and creds.refresh_token:
					try:
						creds.refresh(Request())
						with open(self.token_file, "w") as token:
							token.write(creds.to_json())
					except Exception as refresh_err:
						logger.warning(f"OAuth2 refresh failed: {refresh_err}")
						creds = None # Saltamos al siguiente método si el refresh falla

				if creds and creds.valid:
					self.service = build("drive", "v3", credentials=creds)
					logger.info("CloudSync: Acceso recuperado vía Token soberano.")
					return
			except Exception as e:
				logger.debug(f"Fallo silencioso en intento Token: {e}")

		# 2. INTENTO: Cuenta de Servicio (Modo Headless/Empresa)
		if os.path.exists(self.service_account_file):
			try:
				from google.oauth2 import service_account
				creds = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=scopes)
				self.service = build("drive", "v3", credentials=creds)
				logger.info("CloudSync: Acceso vía Cuenta de Servicio (Headless) activo.")
				return
			except Exception as e:
				logger.warning(f"Fallo en intento Cuenta de Servicio: {e}")

		# 3. INTENTO: OAuth2 Interactivo (Último recurso, requiere intervención)
		if os.path.exists(self.client_secrets_file):
			try:
				from google_auth_oauthlib.flow import InstalledAppFlow
				logger.info("CloudSync: Iniciando flujo interactivo (Requiere intervención del Operador)...")
				flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, scopes)
				creds = flow.run_local_server(port=43303, open_browser=False, success_message="ritual_complete")

				os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
				with open(self.token_file, "w") as token:
					token.write(creds.to_json())

				self.service = build("drive", "v3", credentials=creds)
				logger.info("CloudSync: Acceso interactivo concedido y token guardado.")
				return
			except Exception as e:
				logger.error(f"CloudSync: Fallo total en flujo interactivo: {e}")
				self._emit_pain("cloud_sync_auth_total_failure", str(e))

		# Si llegamos aquí sin self.service, el plugin se deshabilita silenciosamente
		logger.warning("CloudSync: No se han encontrado credenciales válidas en la jerarquía. Plugin inactivo.")
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

	def _on_soul_created(self, zip_path: str) -> None:
		"""Uploads the newly created encrypted kit."""
		if not zip_path:
			return

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
