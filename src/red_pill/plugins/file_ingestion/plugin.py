import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from watchfiles import Change, awatch

import red_pill.config as cfg
from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.notifier import SovereignNotifier
from red_pill.core.plugin_engine import PluginScope, Priority, SovereignPlugin

logger = logging.getLogger(__name__)


class FileIngestionPlugin(SovereignPlugin):
	def __init__(self):
		super().__init__(name="file_ingestion", version="1.0.0", directory=Path(__file__).parent)
		self.queue_manager = CognitiveQueueManager()
		self.watch_tasks: List[asyncio.Task] = []

	@property
	def scopes(self) -> List[PluginScope]:
		return [PluginScope.BACKGROUND]

	@property
	def priority(self) -> Priority:
		return Priority.NORMAL

	@property
	def requested_permissions(self) -> List[str]:
		return ["read_files", "enqueue_tasks"]

	async def init(self) -> None:
		logger.info("[FileIngestion] Initializing plugin...")
		# Ensure ingestion directories exist
		for d in cfg.INGESTION_DIRECTORIES:
			os.makedirs(d, exist_ok=True)
			logger.info(f"[FileIngestion] Watching directory: {d}")

	async def activate(self) -> None:
		logger.info("[FileIngestion] Activating watchdog...")
		if not cfg.INGESTION_DIRECTORIES:
			logger.warning("[FileIngestion] No ingestion directories configured. Plugin idle.")
			return

		# Start an async watcher task for the directories
		task = asyncio.create_task(self._watch_loop())
		self.watch_tasks.append(task)

	async def _watch_loop(self) -> None:
		try:
			# awatch supports multiple directories
			async for changes in awatch(*cfg.INGESTION_DIRECTORIES):
				for change, path in changes:
					# We only care about new or modified files
					if change in (Change.added, Change.modified):
						if os.path.isfile(path) and not path.endswith(".part") and not path.endswith(".tmp"):
							self._enqueue_ingestion(path)
		except asyncio.CancelledError:
			logger.info("[FileIngestion] Watchdog task cancelled.")
		except Exception as e:
			logger.error(f"[FileIngestion] Watchdog error: {e}")

	def _enqueue_ingestion(self, file_path: str) -> None:
		"""Sends the file to the cognitive DAG for background vectorization."""
		logger.info(f"[FileIngestion] Detected file change: {file_path}. Enqueueing ingestion task.")

		# Notify user that ingestion started
		filename = os.path.basename(file_path)
		SovereignNotifier.notify_os("Ingestion Pipeline", f"Detectado nuevo archivo: {filename}.\nIniciando vectorización.", icon="document-new")

		# Create a DAG task for the 'ingestor' minion
		self.queue_manager.enqueue_task(source="plugin", payload={"minion": "ingestor", "kwargs": {"file_path": file_path}}, priority=50)

	async def hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:
		return payload

	async def deactivate(self) -> None:
		logger.info("[FileIngestion] Deactivating watchdog...")
		for task in self.watch_tasks:
			if not task.done():
				task.cancel()
		self.watch_tasks.clear()

	async def uninstall(self, purge: bool = False) -> None:
		await self.deactivate()

	async def export_state(self) -> Dict[str, Any]:
		return {"directories_watched": cfg.INGESTION_DIRECTORIES}
