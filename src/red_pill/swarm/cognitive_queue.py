import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("CognitiveQueue")


class CognitiveQueue:
	"""
	Sovereign Drive Phase 7.1: The Cognitive Queue.
	Evaluates pending tasks autonomously utilizing Bayesian Priority and a Frustration Breaker.
	"""

	def __init__(self, db_path: Path):
		self.db_path = db_path
		self._init_db()

	def _init_db(self):
		"""Initializes the SQLite Schema for autonomous task queuing."""
		with sqlite3.connect(self.db_path) as conn:
			conn.execute("""
                CREATE TABLE IF NOT EXISTS cognitive_tasks (
                    task_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    payload JSON NOT NULL,
                    base_urgency REAL DEFAULT 1.0,
                    expected_info_gain REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'PENDING',
                    failure_count INTEGER DEFAULT 0,
                    cost_accumulator REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
			conn.commit()

	def push_task(self, task_id: str, source_type: str, payload: Dict[str, Any], base_urgency: float = 1.0, expected_info_gain: float = 1.0):
		"""Injects a task into the queue (e.g. from Sentinel, Telegram, or internal Entropy)."""
		with sqlite3.connect(self.db_path) as conn:
			conn.execute(
				"""
                INSERT OR REPLACE INTO cognitive_tasks
                (task_id, source_type, payload, base_urgency, expected_info_gain, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
				(task_id, source_type, json.dumps(payload), base_urgency, expected_info_gain),
			)
			conn.commit()
			logger.info(f"Task {task_id} injected into Cognitive Queue. Source: {source_type}")

	def get_next_task(self) -> Optional[Dict[str, Any]]:
		"""
		Phase 2: Evaluates the queue using (base_urgency * expected_info_gain) heuristic.
		If empty, returns None, which triggers the Right to Silence (Sleep mode).
		"""
		with sqlite3.connect(self.db_path) as conn:
			conn.row_factory = sqlite3.Row
			cursor = conn.execute("""
                SELECT * FROM cognitive_tasks
                WHERE status = 'PENDING'
                ORDER BY (base_urgency * expected_info_gain) DESC
                LIMIT 1
            """)
			row = cursor.fetchone()
			if row:
				# Mark as processing to prevent race conditions in Swarm
				conn.execute("UPDATE cognitive_tasks SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP WHERE task_id = ?", (row["task_id"],))
				conn.commit()
				return dict(row)
			return None

	def mark_frustrated(self, task_id: str, cost_increment: float = 1.0):
		"""
		Phase 3: Frustration Circuit Breaker.
		Increments failures and costs. If thresholds exceeded, marks as FRUSTRATED.
		"""
		MAX_FAILURES = 3
		MAX_COST = 50.0

		with sqlite3.connect(self.db_path) as conn:
			conn.row_factory = sqlite3.Row
			row = conn.execute("SELECT failure_count, cost_accumulator FROM cognitive_tasks WHERE task_id = ?", (task_id,)).fetchone()
			if not row:
				return

			new_fails = row["failure_count"] + 1
			new_cost = row["cost_accumulator"] + cost_increment

			if new_fails >= MAX_FAILURES or new_cost > MAX_COST:
				conn.execute(
					"""
                    UPDATE cognitive_tasks
                    SET status = 'FRUSTRATED', failure_count = ?, cost_accumulator = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                """,
					(new_fails, new_cost, task_id),
				)
				logger.warning(f"Cognitive Loop Broken: Task {task_id} labeled as FRUSTRATED. Reverting to IDLE.")
			else:
				conn.execute(
					"""
                    UPDATE cognitive_tasks
                    SET status = 'PENDING', failure_count = ?, cost_accumulator = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                """,
					(new_fails, new_cost, task_id),
				)
			conn.commit()

	def mark_completed(self, task_id: str):
		"""Closes the task cycle upon success."""
		with sqlite3.connect(self.db_path) as conn:
			conn.execute("UPDATE cognitive_tasks SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP WHERE task_id = ?", (task_id,))
			conn.commit()
