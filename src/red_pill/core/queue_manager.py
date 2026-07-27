import hashlib
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from red_pill.core.paths import get_queue_dir

logger = logging.getLogger(__name__)


class MemoryQueueManager:
	"""
	Dependency-free SQLite Queue for asynchronous memory ingestion.
	Isolates MCP synchronous requests from heavy LLM/Vector DB operations.
	"""

	def __init__(self, db_path: Optional[str] = None):
		if db_path is None:
			# Isolate memory queue from Minion inbox events for better WAL safety.
			self.db_path = str(get_queue_dir() / "bunker_queue.db")
		else:
			self.db_path = db_path

		os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
		self._init_db()

	def _init_db(self) -> None:
		with sqlite3.connect(self.db_path, timeout=30.0) as conn:
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
					category TEXT DEFAULT 'mixed',
					originator TEXT
				)
				"""
			)
			try:
				cursor.execute("ALTER TABLE memory_queue ADD COLUMN category TEXT DEFAULT 'mixed'")
			except sqlite3.OperationalError:
				pass  # Column already exists
			try:
				cursor.execute("ALTER TABLE memory_queue ADD COLUMN originator TEXT")
			except sqlite3.OperationalError:
				pass
			try:
				cursor.execute("ALTER TABLE memory_queue ADD COLUMN model TEXT")
			except sqlite3.OperationalError:
				pass
			try:
				cursor.execute("ALTER TABLE memory_queue ADD COLUMN content_hash TEXT")
			except sqlite3.OperationalError:
				pass
			# Index for fast lookup of pending items
			cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON memory_queue (status)")
			# Idempotency: the same turn can arrive from the deterministic hook AND
			# from the agent's handshake relay. Deduplication must not depend on the
			# model behaving, so it is resolved here, at the sink.
			cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON memory_queue (content_hash, created_at)")
			conn.commit()

	def enqueue_memory(
		self,
		prompt: str,
		response: str,
		role: str,
		category: str = "mixed",
		originator: Optional[str] = None,
		model: Optional[str] = None,
		dedup_window_hours: Optional[float] = 12.0,
	) -> int:
		"""Push a fast memory into the queue. Returns row ID (existing one if duplicate).

		Args:
			category: 'work', 'social', or 'mixed'. Classified by the LLM
				at write-time (not by the sleep cycle's keyword heuristic).
			originator: capture surface (claude_code, opencode, antigravity, telegram…).
			dedup_window_hours: an identical turn arriving inside this window is
				treated as the same turn and not queued twice. Two producers can
				legitimately see the same turn — the editor hook (deterministic)
				and the agent's handshake relay (only if the model remembers) — so
				the guard lives here rather than depending on either behaving.
				`None` dedups against the whole history (for backfills, where the
				original timestamps are old); `0` disables the guard, which is
				what you want if the operator legitimately repeats a turn.
		"""
		if category not in ("work", "social", "mixed"):
			category = "mixed"
		content_hash = hashlib.sha256(f"{prompt}\x00{response}".encode("utf-8", errors="replace")).hexdigest()
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				cursor = conn.cursor()
				if dedup_window_hours is None or dedup_window_hours > 0:
					query = "SELECT id FROM memory_queue WHERE content_hash = ?"
					params: tuple = (content_hash,)
					if dedup_window_hours is not None:
						query += " AND created_at > ?"
						params += (time.time() - dedup_window_hours * 3600,)
					existing = cursor.execute(query + " ORDER BY created_at DESC LIMIT 1", params).fetchone()
					if existing:
						logger.debug(f"Duplicate turn ignored (already queued as row {existing[0]}).")
						return int(existing[0])
				cursor.execute(
					"INSERT INTO memory_queue (prompt, response, role, status, created_at, category, originator, model, content_hash) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
					(prompt, response, role, time.time(), category, originator, model, content_hash),
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
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute(
					"SELECT id, prompt, response, role, category, originator, model FROM memory_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
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
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				cursor = conn.cursor()
				cursor.execute("UPDATE memory_queue SET status = ? WHERE id = ?", (status, item_id))
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to update memory queue item {item_id}: {e}")

	def get_pending_count(self) -> int:
		"""Returns the total number of engrams waiting in the queue."""
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
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
