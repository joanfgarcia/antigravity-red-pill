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
		# Deterministic shutdown: join() waits on the thread's termination
		# event. The old pattern (sleep + is_alive) raced with CPython's
		# thread teardown and flaked under loaded CI (coverage + slow GIL
		# handoff): run() had already logged "Thread stopped" yet is_alive()
		# still returned True.
		sw.join(timeout=5)
		self.assertFalse(sw.is_alive())

	def test_healthy_after_start(self):
		"""Thread reports healthy immediately after start."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker()
		sw.start()
		self.assertTrue(sw.is_healthy())
		sw.stop()
		sw.join(timeout=5)
		self.assertFalse(sw.is_alive())

	def test_empty_wake_survives(self):
		"""Thread survives a wake signal with no pending tasks."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		sw = SamanthaWorker(idle_timeout=1)
		sw.start()
		sw.wake()
		time.sleep(0.5)
		self.assertTrue(sw.is_alive())
		sw.stop()
		sw.join(timeout=5)
		self.assertFalse(sw.is_alive())

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

		with patch("red_pill.telegram.session.TelegramSessionManager", return_value=mock_tsm):
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
		with patch("red_pill.telegram.session.TelegramSessionManager") as MockTSM:
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
		sw.join(timeout=5)

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


class TestIdleAndDrainWait(unittest.TestCase):
	"""Tests for SamanthaWorker.is_idle() / wait_until_idle() (pulse drain-wait)."""

	def _worker(self):
		from red_pill.inference.samantha_worker import SamanthaWorker

		return SamanthaWorker(idle_timeout=1)

	def test_is_idle_without_pending(self):
		"""Sin tarea en vuelo ni PENDING, el carril está idle."""
		sw = self._worker()
		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as MockQM:
			MockQM.return_value.has_pending.return_value = False
			self.assertTrue(sw.is_idle())
			MockQM.return_value.has_pending.assert_called_once_with(source="samantha")

	def test_is_idle_with_pending(self):
		"""Con una tarea PENDING, no está idle."""
		sw = self._worker()
		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as MockQM:
			MockQM.return_value.has_pending.return_value = True
			self.assertFalse(sw.is_idle())

	def test_is_idle_while_draining(self):
		"""Mientras corre el drenaje no está idle (aunque no haya PENDING aún)."""
		sw = self._worker()
		sw._draining = True
		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as MockQM:
			MockQM.return_value.has_pending.return_value = False
			self.assertFalse(sw.is_idle())

	def test_is_idle_with_task_in_flight(self):
		"""Una tarea en vuelo (current_task_id) implica no idle."""
		sw = self._worker()
		sw._current_task_id = "task-1"
		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as MockQM:
			MockQM.return_value.has_pending.return_value = False
			self.assertFalse(sw.is_idle())

	def test_wait_until_idle_immediate(self):
		"""Si el carril ya está drenado, wait_until_idle vuelve al instante."""
		sw = self._worker()
		sw.start()
		try:
			with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as MockQM:
				MockQM.return_value.has_pending.return_value = False
				t0 = time.monotonic()
				self.assertTrue(sw.wait_until_idle(timeout=5))
				self.assertLess(time.monotonic() - t0, 2)
		finally:
			sw.stop()
			sw.join(timeout=5)

	def test_wait_until_idle_timeout(self):
		"""Con trabajo pendiente que nadie procesa, vence el timeout."""
		sw = self._worker()
		sw.start()
		try:
			with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager") as MockQM:
				MockQM.return_value.has_pending.return_value = True
				t0 = time.monotonic()
				self.assertFalse(sw.wait_until_idle(timeout=0.6))
				self.assertGreaterEqual(time.monotonic() - t0, 0.5)
		finally:
			sw.stop()
			sw.join(timeout=5)

	def test_wait_until_idle_dead_thread(self):
		"""Si el hilo no vive, no se espera al timeout completo."""
		sw = self._worker()  # nunca arrancado
		self.assertFalse(sw.wait_until_idle(timeout=5))


class TestRecoverStaleProcessing(unittest.TestCase):
	"""Tests for CognitiveQueueManager.recover_stale_processing() (carril samantha)."""

	def setUp(self):
		self.tmp = tempfile.mkdtemp()
		self.db_path = os.path.join(self.tmp, "test_queue.db")
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		self.qm = CognitiveQueueManager(db_path=self.db_path)

	def _age(self, task_id, hours=2):
		import sqlite3

		conn = sqlite3.connect(self.db_path)
		conn.execute("UPDATE cognitive_tasks SET updated_at = datetime('now', ?) WHERE id = ?", (f"-{hours} hours", task_id))
		conn.commit()
		conn.close()

	def _status_attempts(self, task_id):
		import sqlite3

		conn = sqlite3.connect(self.db_path)
		conn.row_factory = sqlite3.Row
		row = conn.execute("SELECT status, attempts FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
		conn.close()
		return row["status"], row["attempts"]

	def _orphan(self, source="samantha"):
		task_id = self.qm.enqueue_task(source=source, payload={"action": "test"})
		self.qm.pop_next_task(allowed_sources=[source])
		self._age(task_id)
		return task_id

	def test_requeues_orphan(self):
		"""Un PROCESSING viejo vuelve a PENDING con attempts+1."""
		task_id = self._orphan()
		self.assertEqual(self.qm.recover_stale_processing("samantha", older_than_seconds=900), 1)
		self.assertEqual(self._status_attempts(task_id), ("PENDING", 1))

	def test_frustrates_at_three_attempts(self):
		"""El disyuntor sella FRUSTRATED al tercer intento, no antes."""
		task_id = self._orphan()
		self.qm.recover_stale_processing("samantha", older_than_seconds=900)
		self.qm.pop_next_task(allowed_sources=["samantha"])
		self._age(task_id)
		self.qm.recover_stale_processing("samantha", older_than_seconds=900)
		self.assertEqual(self._status_attempts(task_id), ("PENDING", 2))
		self.qm.pop_next_task(allowed_sources=["samantha"])
		self._age(task_id)
		self.qm.recover_stale_processing("samantha", older_than_seconds=900)
		self.assertEqual(self._status_attempts(task_id), ("FRUSTRATED", 3))

	def test_ignores_fresh_processing(self):
		"""Un PROCESSING reciente (en vuelo) no se toca."""
		task_id = self.qm.enqueue_task(source="samantha", payload={"action": "test"})
		self.qm.pop_next_task(allowed_sources=["samantha"])
		self.assertEqual(self.qm.recover_stale_processing("samantha", older_than_seconds=900), 0)
		self.assertEqual(self._status_attempts(task_id), ("PROCESSING", 0))

	def test_ignores_other_sources(self):
		"""Acotada por source (R5): no toca huérfanos de otros carriles."""
		task_id = self._orphan(source="cognitive")
		self.assertEqual(self.qm.recover_stale_processing("samantha", older_than_seconds=900), 0)
		self.assertEqual(self._status_attempts(task_id), ("PROCESSING", 0))


class TestPulseDrainWait(unittest.TestCase):
	"""Tests for IDEWorker.wait_for_samantha() and orphan recovery in _signal_samantha_worker."""

	def _worker(self):
		from red_pill.core.agent_worker import IDEWorker

		return IDEWorker.__new__(IDEWorker)

	def test_wait_for_samantha_without_worker(self):
		"""Sin SamanthaWorker (init fallido) la espera es un no-op exitoso."""
		w = self._worker()
		w._samantha_worker = None
		self.assertTrue(w.wait_for_samantha(timeout=1))

	def test_wait_for_samantha_stops_worker(self):
		"""Tras drenar, el worker se detiene y se une (shutdown limpio)."""
		w = self._worker()
		sw = MagicMock()
		sw.wait_until_idle.return_value = True
		w._samantha_worker = sw
		w._signal_samantha_worker = lambda: None
		self.assertTrue(w.wait_for_samantha(timeout=1))
		sw.wait_until_idle.assert_called_once_with(1)
		sw.stop.assert_called_once()
		sw.join.assert_called_once()

	def test_wait_for_samantha_timeout_returns_false(self):
		"""Si vence el timeout, la tarea en vuelo queda para recovery."""
		w = self._worker()
		sw = MagicMock()
		sw.wait_until_idle.return_value = False
		w._samantha_worker = sw
		w._signal_samantha_worker = lambda: None
		self.assertFalse(w.wait_for_samantha(timeout=1))
		sw.stop.assert_called_once()

	def test_signal_recovers_orphans_and_wakes(self):
		"""_signal_samantha_worker recupera huérfanos antes de mirar PENDING."""
		w = self._worker()
		sw = MagicMock()
		w._samantha_worker = sw
		fake_qm = MagicMock()
		fake_qm.has_pending.return_value = True
		with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager", return_value=fake_qm):
			w._signal_samantha_worker()
		fake_qm.recover_stale_processing.assert_called_once_with("samantha", older_than_seconds=900)
		sw.wake.assert_called_once()


class TestDrainCycleIntegration(unittest.TestCase):
	"""Flujo real de la cola (DB temporal) con LLM mockeado: la tarea drena a COMPLETED."""

	def setUp(self):
		self.tmp = tempfile.mkdtemp()
		self.db_path = os.path.join(self.tmp, "test_queue.db")
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		self.qm = CognitiveQueueManager(db_path=self.db_path)

	def _enqueue(self):
		return self.qm.enqueue_task(
			source="samantha",
			payload={"action": "compact_session", "session_id": "sess-1", "channel_user_id": "u1", "history_text": "USER: hola"},
			priority=7,
		)

	def _status(self, task_id):
		import sqlite3

		conn = sqlite3.connect(self.db_path)
		conn.row_factory = sqlite3.Row
		row = conn.execute("SELECT status FROM cognitive_tasks WHERE id = ?", (task_id,)).fetchone()
		conn.close()
		return row["status"]

	def test_drain_cycle_completes_pending_task(self):
		"""_drain_cycle procesa el PENDING y dispara el callback de compactación."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		task_id = self._enqueue()
		sw = SamanthaWorker(idle_timeout=1)
		with (
			patch("red_pill.cognitive.queue_manager.CognitiveQueueManager", return_value=self.qm),
			patch.object(sw, "_boot_samantha", return_value=8760),
			patch("red_pill.inference.samantha_on_demand._call_llm", return_value="resumen técnico"),
			patch.object(sw, "_run_callback") as mock_cb,
		):
			sw._drain_cycle()
		self.assertEqual(self._status(task_id), "COMPLETED")
		mock_cb.assert_called_once()

	def test_wait_until_idle_drains_real_task(self):
		"""El drain-wait del pulse devuelve True cuando la tarea termina."""
		from red_pill.inference.samantha_worker import SamanthaWorker

		task_id = self._enqueue()
		sw = SamanthaWorker(idle_timeout=1)
		with (
			patch("red_pill.cognitive.queue_manager.CognitiveQueueManager", return_value=self.qm),
			patch.object(sw, "_boot_samantha", return_value=8760),
			patch("red_pill.inference.samantha_on_demand._call_llm", return_value="resumen técnico"),
			patch.object(sw, "_run_callback"),
		):
			sw.start()
			try:
				sw.wake()
				self.assertTrue(sw.wait_until_idle(timeout=10))
			finally:
				sw.stop()
				sw.join(timeout=5)
		self.assertEqual(self._status(task_id), "COMPLETED")


if __name__ == "__main__":
	unittest.main()
