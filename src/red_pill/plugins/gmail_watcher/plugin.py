import logging
import os
import time

from red_pill.memory import MemoryManager
from red_pill.plugins.base import RedPillPlugin

logger = logging.getLogger(__name__)

class GmailWatcherPlugin(RedPillPlugin):
	"""
	Dummy Gmail Watcher Plugin.
	Demonstrates background task capability via the Sovereign Plugin system using systemd timers.
	"""

	def __init__(self):
		super().__init__("gmail_watcher")

	def on_plugin_setup(self):
		"""Called automatically on plugin registration."""
		if not self.config.get("enabled", False):
			logger.info("[GmailWatcher] Plugin is disabled in config.")
		else:
			logger.info("[GmailWatcher] Plugin Enabled. Ready for systemd timer invocations.")

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

