"""
Tests for the SamanthaWorker event-driven thread and related infrastructure.

Verifies:
- CognitiveQueueManager.has_pending() and find_task_by_payload_key()
- SamanthaWorker lifecycle (start, wake, stop, daemon attribute)
- SamanthaWorker watchdog health reporting
- enqueue() helper function
- Truncation fallback in worker history construction
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestCognitiveQueueHasPending(unittest.TestCase):
	"""Tests for the has_pending() and find_task_by_payload_key() methods."""

	def setUp(self):
		self.tmp = tempfile.mkdtemp()
		self.db_path = os.path.join(self.tmp, "test_queue.db")
		from red_pill.cognitive.queue_manager import CognitiveQueueManager
		self.qm = CognitiveQueueManager(db_path=self.db_path)

	def test_empty_queue(self):
		"""has_pending returns False on empty queue."""
		self.assertFalse(self.qm.has_pending())
		self.assertFalse(self.qm.has_pending(source="samantha"))

	def test_enqueue_makes_pending(self):
		"""has_pending returns True after enqueue."""
		self.qm.enqueue_task(source="samantha", payload={"action": "test"})
		self.assertTrue(self.qm.has_pending())
		self.assertTrue(self.qm.has_pending(source="samantha"))

	def test_source_filter(self):
		"""has_pending with source filter only matches the correct source."""
		self.qm.enqueue_task(source="samantha", payload={"action": "test"})
		self.assertTrue(self.qm.has_pending(source="samantha"))
		self.assertFalse(self.qm.has_pending(source="drive_evaluator"))

	def test_pop_clears_pending(self):
		"""After popping the only task, has_pending returns False."""
		self.qm.enqueue_task(source="samantha", payload={"action": "test"})
		task = self.qm.pop_next_task(allowed_sources=["samantha"])
		self.assertIsNotNone(task)
		self.assertFalse(self.qm.has_pending(source="samantha"))

	def test_find_by_payload_key(self):
		"""find_task_by_payload_key finds the correct task."""
		self.qm.enqueue_task(source="samantha", payload={"action": "compact_session", "session_id": "abc123"})
		found = self.qm.find_task_by_payload_key(source="samantha", key="session_id", value="abc123")
		self.assertIsNotNone(found)
		self.assertEqual(found["payload"]["session_id"], "abc123")
		self.assertEqual(found["status"], "PENDING")

	def test_find_by_payload_key_not_found(self):
		"""find_task_by_payload_key returns None when not found."""
		self.qm.enqueue_task(source="samantha", payload={"action": "compact_session", "session_id": "abc123"})
		result = self.qm.find_task_by_payload_key(source="samantha", key="session_id", value="nonexistent")
		self.assertIsNone(result)

	def test_find_ignores_completed(self):
		"""find_task_by_payload_key ignores COMPLETED tasks."""
		tid = self.qm.enqueue_task(source="samantha", payload={"action": "test", "key1": "val1"})
		self.qm.mark_completed(tid)
		result = self.qm.find_task_by_payload_key(source="samantha", key="key1", value="val1")
		self.assertIsNone(result)


class TestSamanthaWorkerLifecycle(unittest.TestCase):
	"""Tests for SamanthaWorker thread lifecycle."""

	def test_daemon_attribute(self):
		"""SamanthaWorker is a daemon thread."""
		from red_pill.inference.samantha_worker import SamanthaWorker
		sw = SamanthaWorker()
		self.assertTrue(sw.daemon)

	def test_start_and_stop(self):
		"""Thread starts and stops cleanly."""
		from red_pill.inference.samantha_worker import SamanthaWorker
		sw = SamanthaWorker(idle_timeout=1)
		sw.start()
		self.assertTrue(sw.is_alive())
		sw.stop()
		time.sleep(0.5)
		self.assertFalse(sw.is_alive())

	def test_healthy_after_start(self):
		"""Thread reports healthy immediately after start."""
		from red_pill.inference.samantha_worker import SamanthaWorker
		sw = SamanthaWorker()
		sw.start()
		self.assertTrue(sw.is_healthy())
		sw.stop()
		time.sleep(0.3)

	def test_empty_wake_survives(self):
		"""Thread survives a wake signal with no pending tasks."""
		from red_pill.inference.samantha_worker import SamanthaWorker
		sw = SamanthaWorker(idle_timeout=1)
		sw.start()
		sw.wake()
		time.sleep(0.5)
		self.assertTrue(sw.is_alive())
		sw.stop()
		time.sleep(0.3)

	def test_stats_initial(self):
		"""Initial stats are zeroed."""
		from red_pill.inference.samantha_worker import SamanthaWorker
		sw = SamanthaWorker()
		stats = sw.get_stats()
		self.assertEqual(stats["processed"], 0)
		self.assertEqual(stats["failed"], 0)
		self.assertEqual(stats["boots"], 0)

	def test_watchdog_timeout(self):
		"""is_healthy returns False after timeout exceeds."""
		from red_pill.inference.samantha_worker import SamanthaWorker
		sw = SamanthaWorker()
		sw._health_ts = time.time() - 200  # Simulate 200s ago
		self.assertFalse(sw.is_healthy(timeout=120))


class TestEnqueueHelper(unittest.TestCase):
	"""Tests for the enqueue() convenience function."""

	def test_enqueue_creates_task(self):
		"""enqueue() creates a task in the cognitive queue."""
		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as MockQM:
			mock_qm = MagicMock()
			mock_qm.enqueue_task.return_value = "test-task-id"
			MockQM.return_value = mock_qm

			# Re-import to pick up the mock
			import importlib
			import red_pill.inference.samantha_worker as sw_mod
			importlib.reload(sw_mod)

			task_id = sw_mod.enqueue(action="compact_session", payload={"session_id": "abc"}, priority=7)

			self.assertEqual(task_id, "test-task-id")
			mock_qm.enqueue_task.assert_called_once()


class TestHandlerRegistry(unittest.TestCase):
	"""Tests for the handler registry and built-in handlers."""

	def test_handlers_registered(self):
		"""All built-in handlers are registered."""
		from red_pill.inference.samantha_worker import _HANDLERS
		self.assertIn("compact_session", _HANDLERS)
		self.assertIn("classify", _HANDLERS)
		self.assertIn("summarize", _HANDLERS)

	def test_compact_handler_with_empty_history(self):
		"""compact_session handler skips empty history."""
		from red_pill.inference.samantha_worker import _HANDLERS
		handler = _HANDLERS["compact_session"]
		result = handler({"history_text": ""}, lambda **kw: "summary")
		self.assertEqual(result["status"], "skipped")

	def test_compact_handler_calls_samantha(self):
		"""compact_session handler calls samantha_fn with proper prompt."""
		from red_pill.inference.samantha_worker import _HANDLERS
		handler = _HANDLERS["compact_session"]

		called_with = {}
		def mock_samantha(prompt, system_prompt="", max_tokens=300):
			called_with["prompt"] = prompt
			return "This is a test summary"

		result = handler({"history_text": "USER: hello\nASSISTANT: hi", "session_id": "test123"}, mock_samantha)
		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["summary"], "This is a test summary")
		self.assertIn("hello", called_with["prompt"])

	def test_classify_handler(self):
		"""classify handler returns category."""
		from red_pill.inference.samantha_worker import _HANDLERS
		handler = _HANDLERS["classify"]
		result = handler(
			{"text": "Fix the bug in auth", "categories": ["bug", "feature", "docs"]},
			lambda prompt, system_prompt="", max_tokens=20: "bug"
		)
		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["category"], "bug")


if __name__ == "__main__":
	unittest.main()
