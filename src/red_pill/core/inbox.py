import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

import red_pill.config as cfg

logger = logging.getLogger(__name__)


class MinionInbox:
	"""
	Lightweight SQLite Inbox for background swarm operations.
	Completely bypasses Qdrant to avoid vectorizing ephemeral JSON/text reports.
	"""

	def __init__(self, db_path: Optional[str] = None):
		if db_path is None:
			# Default to the brain path, alongside the vector DB files
			self.db_path = os.path.join(cfg.BRAIN_PATH, "minion_inbox.db")
		else:
			self.db_path = db_path
		
		# Ensure the directory exists
		os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
		self._init_db()

	def _init_db(self) -> None:
		with sqlite3.connect(self.db_path) as conn:
			cursor = conn.cursor()
			cursor.execute(
				"""
				CREATE TABLE IF NOT EXISTS inbox (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					event_id TEXT,
					source TEXT,
					status TEXT,
					content TEXT,
					is_read INTEGER DEFAULT 0,
					timestamp REAL
				)
				"""
			)
			cursor.execute("CREATE INDEX IF NOT EXISTS idx_is_read ON inbox (is_read)")
			conn.commit()

	def drop_report(self, event_id: str, source: str, status: str, content: str) -> None:
		"""Save a fire-and-forget report from a background minion."""
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute(
					"INSERT INTO inbox (event_id, source, status, content, timestamp) VALUES (?, ?, ?, ?, ?)",
					(event_id, source, status, content, time.time()),
				)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to drop report in MinionInbox: {e}")

	def get_unread(self, limit: int = 50) -> List[Dict[str, Any]]:
		"""Fetch unread background reports."""
		reports = []
		try:
			with sqlite3.connect(self.db_path) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute(
					"SELECT id, event_id, source, status, content, is_read, timestamp FROM inbox WHERE is_read = 0 ORDER BY timestamp DESC LIMIT ?", (limit,)
				)
				for row in cursor.fetchall():
					reports.append(dict(row))
		except Exception as e:
			logger.error(f"Failed to fetch unread reports: {e}")
		return reports

	def mark_as_read(self, report_ids: List[int]) -> None:
		"""Mark reports as read (they can be purged later)."""
		if not report_ids:
			return
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				placeholders = ",".join("?" * len(report_ids))
				cursor.execute(f"UPDATE inbox SET is_read = 1 WHERE id IN ({placeholders})", report_ids)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to mark reports as read: {e}")

	def purge_read(self) -> None:
		"""Delete all read messages to keep the inbox completely sterile."""
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute("DELETE FROM inbox WHERE is_read = 1")
				deleted = cursor.rowcount
				conn.commit()
				if deleted > 0:
					logger.debug(f"Purged {deleted} obsolete reports from MinionInbox.")
		except Exception as e:
			logger.error(f"Failed to purge MinionInbox: {e}")
