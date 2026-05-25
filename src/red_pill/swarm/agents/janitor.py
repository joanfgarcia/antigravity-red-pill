import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from red_pill.swarm.base import Minion

logger = logging.getLogger(__name__)


class JanitorMinion(Minion):
	"""
	Specialized Minion for system maintenance and garbage collection.
	Responsible for keeping the ecosystem clean (SQLite events, temp files, logs).
	"""

	name: str = "Janitor"
	specialization: str = "System Maintenance and Garbage Collection"

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""
		Executes a cleaning cycle.
		"""
		self.log("--- [Janitor] Initializing Cleaning Cycle ---")

		days_to_keep = kwargs.get("days_to_keep", 7)
		results = {
			"db_events_purged": 0,
			"scratch_files_purged": 0,
			"status": "success",
		}

		# 1. Purge events.db
		events_db_path = Path.home() / ".local" / "share" / "neon-link" / "events.db"
		if events_db_path.exists():
			purged = self._purge_events_db(events_db_path, days_to_keep)
			results["db_events_purged"] = purged
			self.log(f"Purged {purged} stale events from {events_db_path.name}")
		else:
			self.log(f"Database {events_db_path} not found. Skipping DB purge.")

		# 2. Purge scratch folder
		scratch_path = Path.home() / "tmp" / "scratch"
		if scratch_path.exists() and scratch_path.is_dir():
			purged_files = self._purge_scratch_folder(scratch_path, days_to_keep)
			results["scratch_files_purged"] = purged_files
			self.log(f"Purged {purged_files} old files from {scratch_path}")

		return results

	def _purge_events_db(self, db_path: Path, days: int) -> int:
		try:
			conn = sqlite3.connect(db_path)
			cursor = conn.cursor()
			cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

			cursor.execute("DELETE FROM inbox WHERE status IN ('PROCESSED', 'DEAD', 'DELIVERED_BACKGROUND') AND created_at < ?", (cutoff_date,))
			inbox_deleted = cursor.rowcount

			cursor.execute("DELETE FROM outbox WHERE status IN ('SENT', 'DEAD') AND created_at < ?", (cutoff_date,))
			outbox_deleted = cursor.rowcount

			cursor.execute("DELETE FROM processed_firebase_messages WHERE processed_at < ?", (cutoff_date,))
			processed_fb_deleted = cursor.rowcount

			conn.commit()
			conn.close()

			return inbox_deleted + outbox_deleted + processed_fb_deleted
		except Exception as e:
			logger.error(f"[Janitor] Failed to purge events.db: {e}")
			return 0

	def _purge_scratch_folder(self, scratch_dir: Path, days: int) -> int:
		deleted_count = 0
		now = datetime.now().timestamp()
		cutoff_time = now - (days * 86400)

		try:
			for item in scratch_dir.iterdir():
				try:
					if item.stat().st_mtime < cutoff_time:
						if item.is_file():
							item.unlink()
						elif item.is_dir():
							shutil.rmtree(item)
						deleted_count += 1
				except Exception as e:
					logger.error(f"[Janitor] Failed to delete {item}: {e}")
		except Exception as e:
			logger.error(f"[Janitor] Failed to read scratch folder {scratch_dir}: {e}")

		return deleted_count
