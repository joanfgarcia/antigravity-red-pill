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

		# 3. Rotate and clean up log files (rotate if size > 10MB, delete if older than 30 days)
		log_results = self._rotate_and_cleanup_logs(max_size_bytes=10 * 1024 * 1024, days_to_keep=30)
		results.update(log_results)

		return results

	def _rotate_and_cleanup_logs(self, max_size_bytes: int, days_to_keep: int) -> Dict[str, Any]:
		targets = [
			Path.home() / ".local/share/red-pill/daemon/output.log",
			Path.home() / ".local/share/red-pill/daemon/error.log",
			Path.home() / ".agent/bunker_daemon.log",
			Path.home() / ".agent/bunker_daemon_error.log",
		]
		rotated_count = 0
		purged_count = 0

		for log_path in targets:
			if log_path.exists() and log_path.is_file():
				# 1. Rotate if file size exceeds the limit
				if log_path.stat().st_size > max_size_bytes:
					try:
						self.log(f"Log file {log_path} exceeds size limit. Rotating...")
						self._rotate_file_copytruncate(log_path)
						rotated_count += 1
					except Exception as e:
						logger.error(f"[Janitor] Failed to rotate {log_path}: {e}")

				# 2. Clean up old rotated logs in the same directory
				try:
					purged = self._cleanup_old_rotated_logs(log_path.parent, log_path.name, days_to_keep)
					purged_count += purged
				except Exception as e:
					logger.error(f"[Janitor] Failed to cleanup rotated logs for {log_path}: {e}")

		return {"logs_rotated": rotated_count, "old_logs_purged": purged_count}

	def _rotate_file_copytruncate(self, log_path: Path):
		# Standard rotation logic: Shift backups log.3 -> log.4, log.2 -> log.3, log.1 -> log.2
		for i in range(3, 0, -1):
			old_file = log_path.with_name(f"{log_path.name}.{i}")
			new_file = log_path.with_name(f"{log_path.name}.{i + 1}")
			if old_file.exists():
				try:
					if new_file.exists():
						new_file.unlink()
					old_file.rename(new_file)
				except Exception as e:
					logger.error(f"[Janitor] Failed to shift log backup {old_file} to {new_file}: {e}")

		# Copy active to log.1
		backup_1 = log_path.with_name(f"{log_path.name}.1")
		try:
			shutil.copy2(log_path, backup_1)
		except Exception as e:
			logger.error(f"[Janitor] Failed to copy {log_path} to {backup_1}: {e}")
			raise e

		# Truncate active file in-place
		try:
			with open(log_path, "w"):
				pass
		except Exception as e:
			logger.error(f"[Janitor] Failed to truncate {log_path}: {e}")
			raise e

	def _cleanup_old_rotated_logs(self, folder: Path, base_name: str, days: int) -> int:
		purged_count = 0
		cutoff_time = datetime.now().timestamp() - (days * 86400)
		for item in folder.iterdir():
			if item.is_file() and item.name.startswith(base_name) and item.name != base_name:
				# It is a rotated log file (e.g. log.1, log.2)
				try:
					if item.stat().st_mtime < cutoff_time:
						item.unlink()
						purged_count += 1
						self.log(f"Deleted old rotated log: {item.name}")
				except Exception as e:
					logger.error(f"[Janitor] Failed to delete rotated log {item}: {e}")
		return purged_count

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
