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
			# Sovereign Pod path inside sharing storage repository
			self.db_path = os.path.join(cfg._IA_DIR, "storage", "queue", "minion_inbox.db")
		else:
			self.db_path = db_path

		# Ensure the directory exists
		os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
		self._init_db()

	def _init_db(self) -> None:
		with sqlite3.connect(self.db_path) as conn:
			cursor = conn.cursor()
			# Enable Write-Ahead Logging for graceful concurrency across minions
			cursor.execute("PRAGMA journal_mode=WAL;")
			cursor.execute("PRAGMA synchronous=NORMAL;")
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
		"""Retrieve unread reports WITHOUT marking them as read (non-destructive peek)."""
		reports = []
		try:
			with sqlite3.connect(self.db_path) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute(
					"SELECT id, event_id, source, status, content, is_read, timestamp FROM inbox WHERE is_read = 0 ORDER BY timestamp DESC LIMIT ?",
					(limit,),
				)
				rows = cursor.fetchall()
				reports = [dict(row) for row in rows]
		except Exception as e:
			logger.error(f"Failed to get unread reports: {e}")
		return reports

	def mark_as_read(self, report_ids: List[int]) -> None:
		"""Mark specific reports as read by ID."""
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				placeholders = ",".join("?" * len(report_ids))
				cursor.execute(f"UPDATE inbox SET is_read = 1 WHERE id IN ({placeholders})", report_ids)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to mark reports as read: {e}")

	def pop_unread(self, limit: int = 50) -> List[Dict[str, Any]]:
		"""Retrieve unread reports and mark them as read atomically."""
		reports = []
		try:
			with sqlite3.connect(self.db_path) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				# Fetch inside transaction
				cursor.execute(
					"SELECT id, event_id, source, status, content, is_read, timestamp FROM inbox WHERE is_read = 0 ORDER BY timestamp DESC LIMIT ?",
					(limit,),
				)
				rows = cursor.fetchall()
				if rows:
					report_ids = [row["id"] for row in rows]
					placeholders = ",".join("?" * len(report_ids))
					cursor.execute(f"UPDATE inbox SET is_read = 1 WHERE id IN ({placeholders})", report_ids)
					reports = [dict(row) for row in rows]
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to pop unread reports: {e}")
		return reports

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
