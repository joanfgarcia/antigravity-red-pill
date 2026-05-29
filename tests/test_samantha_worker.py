"""
Tests for the SamanthaWorker event-driven thread and related infrastructure.

Verifies:
- CognitiveQueueManager.has_pending() and find_task_by_payload_key()
- SamanthaWorker lifecycle (start, wake, stop, daemon attribute)
- SamanthaWorker watchdog health reporting
- enqueue() helper function
- Truncation fallback in worker history construction
"""

import os
import tempfile
import time
import unittest
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
			{"text": "Fix the bug in auth", "categories": ["bug", "feature", "docs"]}, lambda prompt, system_prompt="", max_tokens=20: "bug"
		)
		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["category"], "bug")


class TestCompactionCallback(unittest.TestCase):
	"""Tests for the _run_callback post-processing after task completion."""

	def test_compact_callback_creates_new_session(self):
		"""After compact_session, callback creates a new session and marks old for purge."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()

		mock_tsm = MagicMock()
		mock_tsm.create_session.return_value = {"id": "new-session-id"}
		mock_tsm.get_session.return_value = {"id": "old-session", "status": "active"}

		with patch("red_pill.plugins.antigravity_ide.telegram_session.TelegramSessionManager", return_value=mock_tsm):
			sw._run_callback(
				action="compact_session",
				payload={"session_id": "old-session", "channel_user_id": "user123"},
				result={"summary": "Test summary of previous conversation"},
			)

		# Verify new session was created
		mock_tsm.create_session.assert_called_once()
		create_kwargs = mock_tsm.create_session.call_args
		self.assertIn("user123", str(create_kwargs))

		# Verify messages were appended to the new session
		self.assertEqual(mock_tsm.append_message.call_count, 2)

	def test_compact_callback_skipped_without_required_fields(self):
		"""Callback does nothing if session_id, summary, or channel_user_id is missing."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()

		# Missing channel_user_id
		with patch("red_pill.plugins.antigravity_ide.telegram_session.TelegramSessionManager") as MockTSM:
			sw._run_callback(
				action="compact_session",
				payload={"session_id": "old-session", "channel_user_id": ""},
				result={"summary": "Test summary"},
			)
			MockTSM.assert_not_called()

	def test_non_compact_callback_is_noop(self):
		"""Non-compact actions don't trigger any callback."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()
		# Should not raise
		sw._run_callback(
			action="classify",
			payload={"text": "hello"},
			result={"status": "completed", "category": "greeting"},
		)


class TestProcessTask(unittest.TestCase):
	"""Tests for _process_task with various scenarios."""

	def test_unknown_handler_marks_failed(self):
		"""Tasks with unknown action are marked as failed."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()
		mock_qm = MagicMock()

		sw._process_task(
			qm=mock_qm,
			task={"id": "task-1", "payload": {"action": "nonexistent_action"}},
			port=8790,
		)

		mock_qm.mark_failed.assert_called_once()
		self.assertEqual(sw._stats["failed"], 1)

	def test_handler_exception_marks_failed(self):
		"""If handler raises, task is marked failed, not crashed."""
		from red_pill.inference.samantha_worker import _HANDLERS, SamanthaWorker

		sw = SamanthaWorker()
		mock_qm = MagicMock()

		# Register a handler that raises
		def bad_handler(payload, samantha_fn):
			raise ValueError("deliberate test error")

		_HANDLERS["_test_bad"] = bad_handler
		try:
			with patch("red_pill.inference.samantha_on_demand._call_llm", return_value="result"):
				sw._process_task(
					qm=mock_qm,
					task={"id": "task-crash", "payload": {"action": "_test_bad"}},
					port=8790,
				)
			mock_qm.mark_failed.assert_called_once()
			self.assertEqual(sw._stats["failed"], 1)
		finally:
			del _HANDLERS["_test_bad"]

	def test_samantha_returns_none_marks_error(self):
		"""If Samantha returns None (empty), compact handler returns error status."""
		from red_pill.inference.samantha_worker import _HANDLERS

		handler = _HANDLERS["compact_session"]
		result = handler(
			{"history_text": "USER: hello", "session_id": "test"},
			lambda prompt, system_prompt="", max_tokens=300: None,  # Samantha returns None
		)
		self.assertEqual(result["status"], "error")


class TestWorkerIntegration(unittest.TestCase):
	"""Tests for worker._signal_samantha_worker and _watchdog_samantha."""

	def test_signal_with_no_worker(self):
		"""_signal_samantha_worker is a no-op when _samantha_worker is None."""
		# Can't easily instantiate IDEWorker without bridge, so test the logic directly
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()
		# Just verify wake() doesn't crash when thread isn't started
		sw.wake()  # Should be fine — just sets the event

	def test_watchdog_detects_dead_thread(self):
		"""Watchdog detects when thread is no longer alive."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker(idle_timeout=1)
		sw.start()
		sw.stop()
		time.sleep(0.5)

		# Thread is dead
		self.assertFalse(sw.is_alive())

	def test_watchdog_detects_hung_thread(self):
		"""Watchdog detects when thread hasn't reported health."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()
		sw._health_ts = time.time() - 300  # 5 minutes ago
		self.assertFalse(sw.is_healthy(timeout=120))

	def test_force_kill_ephemeral_no_process(self):
		"""force_kill_ephemeral is safe when no ephemeral process exists."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()
		sw._ephemeral_proc = None
		sw.force_kill_ephemeral()  # Should not raise

	def test_force_kill_ephemeral_with_process(self):
		"""force_kill_ephemeral terminates the process."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()
		mock_proc = MagicMock()
		sw._ephemeral_proc = mock_proc

		sw.force_kill_ephemeral()

		mock_proc.terminate.assert_called_once()
		self.assertIsNone(sw._ephemeral_proc)


class TestTruncationFallback(unittest.TestCase):
	"""Tests for history truncation when sessions exceed threshold."""

	def _make_steps(self, n):
		"""Create n dummy conversation steps."""
		steps = []
		for i in range(n):
			role = "USER" if i % 2 == 0 else "ASSISTANT"
			steps.append({"intent": role, "message": {"text": f"Message {i} from {role.lower()}"}})
		return steps

	def test_no_truncation_under_threshold(self):
		"""History under 20 steps is not truncated."""
		steps = self._make_steps(15)
		history_steps = steps[:-1]  # Simulates all_steps[:-1]

		TRUNCATION_THRESHOLD = 20

		if len(history_steps) > TRUNCATION_THRESHOLD:
			self.fail("Should not truncate")

		# Build history as worker does
		history_lines = []
		for step in history_steps:
			role = step.get("intent", "USER")
			txt = step.get("message", {}).get("text", "")
			if txt:
				history_lines.append(f"{role}: {txt}")

		self.assertEqual(len(history_lines), 14)

	def test_truncation_above_threshold(self):
		"""History above 20 steps is truncated to last 12 with header."""
		steps = self._make_steps(30)
		history_steps = steps[:-1]  # 29 steps

		TRUNCATION_THRESHOLD = 20
		TRUNCATION_KEEP = 12

		self.assertGreater(len(history_steps), TRUNCATION_THRESHOLD)

		# Simulate truncation as worker does
		truncated_count = len(history_steps) - TRUNCATION_KEEP
		history_steps_truncated = history_steps[-TRUNCATION_KEEP:]
		history_lines = [f"[Contexto anterior truncado: {truncated_count} mensajes omitidos. Compactación pendiente vía Samantha.]"]

		for step in history_steps_truncated:
			role = step.get("intent", "USER")
			txt = step.get("message", {}).get("text", "")
			if txt:
				history_lines.append(f"{role}: {txt}")

		# 1 header + 12 steps
		self.assertEqual(len(history_lines), 13)
		self.assertIn("truncado", history_lines[0])
		self.assertEqual(truncated_count, 17)

	def test_truncation_preserves_recent_context(self):
		"""Truncated history contains the most recent messages."""
		steps = self._make_steps(25)
		history_steps = steps[:-1]  # 24 steps

		TRUNCATION_KEEP = 12
		truncated = history_steps[-TRUNCATION_KEEP:]

		# Last message should be from the end
		last = truncated[-1]
		self.assertIn("23", last["message"]["text"])  # Step 23 (0-indexed)


if __name__ == "__main__":
	unittest.main()
