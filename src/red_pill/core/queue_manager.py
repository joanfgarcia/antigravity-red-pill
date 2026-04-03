import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

import red_pill.config as cfg

logger = logging.getLogger(__name__)


class MemoryQueueManager:
	"""
	Dependency-free SQLite Queue for asynchronous memory ingestion.
	Isolates MCP synchronous requests from heavy LLM/Vector DB operations.
	"""

	def __init__(self, db_path: Optional[str] = None):
		if db_path is None:
			# Isolate memory queue from Minion inbox events for better WAL safety.
			self.db_path = os.path.join(cfg._IA_DIR, "storage", "queue", "bunker_queue.db")
		else:
			self.db_path = db_path

		os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
		self._init_db()

	def _init_db(self) -> None:
		with sqlite3.connect(self.db_path) as conn:
			cursor = conn.cursor()
			cursor.execute("PRAGMA journal_mode=WAL;")
			cursor.execute("PRAGMA synchronous=NORMAL;")
			cursor.execute(
				"""
				CREATE TABLE IF NOT EXISTS memory_queue (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					prompt TEXT NOT NULL,
					response TEXT NOT NULL,
					role TEXT NOT NULL,
					status TEXT DEFAULT 'pending',
					created_at REAL,
					category TEXT DEFAULT 'mixed'
				)
				"""
			)
			# v6.3.8: Add category column to existing databases (migration)
			try:
				cursor.execute("ALTER TABLE memory_queue ADD COLUMN category TEXT DEFAULT 'mixed'")
			except sqlite3.OperationalError:
				pass  # Column already exists
			# Index for fast lookup of pending items
			cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON memory_queue (status)")
			conn.commit()

	def enqueue_memory(self, prompt: str, response: str, role: str, category: str = "mixed") -> int:
		"""Push a fast memory into the queue. Returns row ID.

		Args:
			category: 'work', 'social', or 'mixed'. Classified by the LLM
				at write-time (not by the sleep cycle's keyword heuristic).
		"""
		if category not in ("work", "social", "mixed"):
			category = "mixed"
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute(
					"INSERT INTO memory_queue (prompt, response, role, status, created_at, category) VALUES (?, ?, ?, 'pending', ?, ?)",
					(prompt, response, role, time.time(), category),
				)
				conn.commit()
				return cursor.lastrowid or 0
		except Exception as e:
			logger.error(f"Failed to enqueue memory: {e}")
			return -1

	def dequeue_pending(self, limit: int = 10) -> List[Dict[str, Any]]:
		"""Fetch pending memories to process them."""
		items = []
		try:
			with sqlite3.connect(self.db_path) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute(
					"SELECT id, prompt, response, role, category FROM memory_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
					(limit,),
				)
				for row in cursor.fetchall():
					items.append(dict(row))
		except Exception as e:
			logger.error(f"Failed to dequeue memory queue: {e}")
		return items

	def update_status(self, item_id: int, status: str) -> None:
		"""Mark item as completed or error."""
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute("UPDATE memory_queue SET status = ? WHERE id = ?", (status, item_id))
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to update memory queue item {item_id}: {e}")

	def get_pending_count(self) -> int:
		"""Returns the total number of engrams waiting in the queue."""
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute("SELECT COUNT(*) FROM memory_queue WHERE status = 'pending'")
				row = cursor.fetchone()
				return row[0] if row else 0
		except Exception as e:
			logger.error(f"Failed to count pending queue: {e}")
			return -1

	def process_pending(self, limit: int = 10) -> List[Dict[str, Any]]:
		"""Defensive alias for dequeue_pending to avoid legacy AttributeErrors."""
		return self.dequeue_pending(limit=limit)
