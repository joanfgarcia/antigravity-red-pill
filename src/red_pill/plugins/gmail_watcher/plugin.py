import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.core.plugin_engine import PluginScope, SovereignPlugin
from red_pill.memory import MemoryManager

logger = logging.getLogger(__name__)

class GmailWatcherPlugin(SovereignPlugin):
	"""
	Dummy Gmail Watcher Plugin.
	Demonstrates background task capability via the Sovereign Plugin system using systemd timers.
	"""

	def __init__(self, name: str = "gmail_watcher", version: str = "1.0", directory: Optional[Path] = None):
		super().__init__(name, version, directory or Path("."))

	@property
	def scopes(self) -> List[PluginScope]:
		return [PluginScope.BACKGROUND]

	@property
	def requested_permissions(self) -> List[str]:
		return ["api:gmail:read", "qdrant:write:signal_memories"]

	async def init(self) -> None:
		if not self.config.get("enabled", False):
			logger.info("[GmailWatcher] Plugin is disabled in config.")
		else:
			logger.info("[GmailWatcher] Plugin Enabled. Ready for systemd timer invocations.")

	async def activate(self) -> None:
		pass

	async def deactivate(self) -> None:
		pass

	async def uninstall(self, purge: bool = False) -> None:
		pass

	async def export_state(self) -> Dict[str, Any]:
		return {}

	async def hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:
		return payload

	def poll(self):
		"""
		One-shot execution to check for new emails.
		This should be triggered by a systemd --user timer.
		"""
		if not self.config.get("enabled", False):
			logger.debug("[GmailWatcher] Plugin is disabled. Skipping poll.")
			return

		email = self.config.get("email_account", "unknown@domain.com")
		logger.info(f"[GmailWatcher] Polling for new emails for {email}...")

		# Simulate a failure occasionally to test the Muted PainSignal / AutoHealer
		if int(time.time()) % 5 == 0:
			logger.warning("[GmailWatcher] Simulated OAuth Error. Submitting pain signal.")
			mgr = MemoryManager()
			# Emitting a MUTED pain signal so it goes to MinionInbox for the AutoHealer
			mgr.inject_signal(
				name="cloud_sync_error_gmail",
				intensity=6.0,
				signal_type="pain",
				source="GmailWatcher",
				muted=True
			)
		else:
			logger.debug("[GmailWatcher] No new emails.")

	def generate_systemd_units(self):
		"""Generates the systemd user service and timer definitions for sovereignty."""
		service_content = f"""[Unit]
Description=Red Pill Gmail Watcher
After=network.target

[Service]
Type=oneshot
ExecStart=uv run python -c "from red_pill.plugins.gmail_watcher import GmailWatcherPlugin; GmailWatcherPlugin().poll()"
WorkingDirectory={os.getcwd()}
"""
		timer_content = """[Unit]
Description=Run Gmail Watcher periodically

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
"""
		return {"service": service_content, "timer": timer_content}

