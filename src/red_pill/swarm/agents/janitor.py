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

		# 4. Sweep orphaned parents in Qdrant (work and social collections)
		try:
			from red_pill.memory import MemoryManager

			memory_manager = MemoryManager()
			purged_work = self._cleanup_orphaned_parents(memory_manager, "work_memories")
			purged_social = self._cleanup_orphaned_parents(memory_manager, "social_memories")
			results["orphaned_parents_purged"] = purged_work + purged_social
			self.log(f"Purged {purged_work} orphaned parents from work_memories and {purged_social} from social_memories.")
		except Exception as e:
			logger.error(f"[Janitor] Failed to execute orphaned parent sweep: {e}")

		# 5. Archive and decouple old SQLite interactions
		try:
			archived = self.archive_old_sqlite_interactions()
			results["sqlite_interactions_archived"] = archived
			self.log(f"Archived {archived} old interactions from SQLite to universal_history.jsonl.")
		except Exception as e:
			logger.error(f"[Janitor] Failed to execute SQLite interactions archiving: {e}")

		# 6. Queue hygiene: autolimpieza de bunker_queue.db (COMPLETED/FRUSTRATED
		# antiguos fuera; PROCESSING colgado >24h → FRUSTRATED + señal de dolor).
		try:
			from red_pill.cognitive.queue_manager import CognitiveQueueManager

			hygiene = CognitiveQueueManager().purge_hygiene()
			results.update(hygiene)
			self.log(
				f"Queue hygiene: {hygiene['completed_purged']} completed y {hygiene['frustrated_purged']} "
				f"frustrated purgados, {hygiene['stuck_marked']} colgados marcados FRUSTRATED."
			)
			if hygiene["stuck_marked"]:
				try:
					from red_pill.memory import MemoryManager

					MemoryManager().inject_signal(
						name="queue_stuck_tasks",
						intensity=6.0,
						signal_type="pain",
						source="Janitor",
						originator=f"queue_hygiene ({hygiene['stuck_marked']} tareas colgadas en PROCESSING)",
					)
				except Exception as sig_err:
					logger.warning(f"[Janitor] Failed to inject queue_stuck_tasks signal: {sig_err}")
		except Exception as e:
			logger.error(f"[Janitor] Failed to execute queue hygiene: {e}")

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

	def _cleanup_orphaned_parents(self, memory_manager, collection_name: str) -> int:
		"""
		Scans all raw_parent engrams in collection_name.
		For each parent, checks if any of its children (listed in associations) exist in work_memories or social_memories.
		If all child engrams have eroded/been deleted, deletes the parent engram.
		"""
		from qdrant_client.http import models

		deleted_count = 0
		if not memory_manager.client.collection_exists(collection_name):
			return 0
		try:
			offset = None
			parent_points = []
			while True:
				records, next_offset = memory_manager.client.scroll(
					collection_name=collection_name,
					scroll_filter=models.Filter(must=[models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent"))]),
					limit=100,
					offset=offset,
					with_payload=True,
					with_vectors=False,
				)
				parent_points.extend(records)
				if next_offset is None:
					break
				offset = next_offset

			for parent in parent_points:
				payload = parent.payload or {}
				associations = payload.get("associations", [])
				child_ids = []
				for assoc in associations:
					if isinstance(assoc, dict):
						child_ids.append(assoc.get("id"))
					else:
						child_ids.append(str(assoc))

				if not child_ids:
					try:
						memory_manager.client.delete(collection_name=collection_name, points_selector=models.PointIdsList(points=[parent.id]))
						deleted_count += 1
					except Exception:
						pass
					continue

				child_exists = False
				for col in ["work_memories", "social_memories"]:
					try:
						found = memory_manager.client.retrieve(collection_name=col, ids=child_ids, with_payload=False, with_vectors=False)
						if found:
							child_exists = True
							break
					except Exception:
						pass

				if not child_exists:
					try:
						memory_manager.client.delete(collection_name=collection_name, points_selector=models.PointIdsList(points=[parent.id]))
						deleted_count += 1
					except Exception:
						pass

		except Exception as e:
			logger.error(f"[Janitor] Failed orphaned parents sweep in {collection_name}: {e}")
		return deleted_count

	def archive_old_sqlite_interactions(self) -> int:
		"""
		Decouples older conversations from SQLite interactions table.
		Appends logs older than 30 days to <agent_core>/history/universal_history.jsonl
		(resolved via paths.get_aleth_core_root) and purges them from the hot SQLite
		database to avoid bloat.
		"""
		import json

		from red_pill.core.paths import get_aleth_core_root, get_db_dir

		db_path = get_db_dir() / "bunker.db"
		if not db_path.exists():
			return 0

		archived_count = 0
		try:
			conn = sqlite3.connect(str(db_path))
			cursor = conn.cursor()

			# Check if interactions table exists
			cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interactions'")
			if not cursor.fetchone():
				conn.close()
				return 0

			cutoff = datetime.utcnow() - timedelta(days=30)
			cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

			cursor.execute("SELECT user_prompt, agent_response, timestamp, model FROM interactions WHERE timestamp < ?", (cutoff_str,))
			rows = cursor.fetchall()

			if rows:
				archive_dir = get_aleth_core_root() / "history"
				archive_dir.mkdir(parents=True, exist_ok=True)
				archive_file = archive_dir / "universal_history.jsonl"

				with open(archive_file, "a") as f:
					for row in rows:
						item = {"timestamp": row[2], "user_prompt": row[0], "agent_response": row[1], "model": row[3] or "unknown"}
						f.write(json.dumps(item) + "\n")
						archived_count += 1

				cursor.execute("DELETE FROM interactions WHERE timestamp < ?", (cutoff_str,))
				conn.commit()
			conn.close()
		except Exception as e:
			logger.error(f"[Janitor] Failed to archive SQLite interactions: {e}")
		return archived_count
