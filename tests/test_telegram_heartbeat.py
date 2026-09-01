"""
Tests for D21 (decoupled heartbeat thread + activity lease) and D23
(commit-pre-prompt) — RFC_TELEGRAM_RESILIENCE, slice mínimo Fase 1.

Covers:
  - _touch_lease updates the monotonic lease touch
  - heartbeat thread beats only while the lease is fresh (falls silent when expired)
  - _process_via_bridge commits the transaction BEFORE the bridge call (D23)
  - commit-pre-prompt frees events.db so neon-link ingest/drain is not blocked
"""

import sqlite3
import time
from unittest.mock import MagicMock

import pytest

import red_pill.plugins.antigravity_ide.worker as worker_module
from red_pill.plugins.antigravity_ide.worker import IDEWorker


@pytest.fixture
def mock_db(tmp_path, monkeypatch):
	db_path = tmp_path / "events.db"
	conn = sqlite3.connect(str(db_path))
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS inbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			message_id TEXT UNIQUE,
			channel TEXT NOT NULL,
			channel_user_id TEXT NOT NULL,
			cascade_id TEXT,
			payload TEXT NOT NULL,
			status TEXT DEFAULT 'PENDING',
			retries INTEGER DEFAULT 0,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
		"""
	)
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS outbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			channel TEXT,
			channel_user_id TEXT,
			cascade_id TEXT,
			payload TEXT
		)
		"""
	)
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS telegram_sessions (
			channel_user_id TEXT PRIMARY KEY,
			cascade_id TEXT,
			cascade_type TEXT,
model TEXT,
			backend TEXT,
			accumulated_len INTEGER
		)
		"""
	)
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS system_health (
			service_name TEXT PRIMARY KEY,
			last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
		"""
	)
	conn.commit()
	conn.close()

	monkeypatch.setattr(worker_module, "DB_PATH", db_path)
	return db_path


class TestHeartbeatLease:
	def test_touch_lease_updates_touch(self):
		worker = IDEWorker.__new__(IDEWorker)
		worker._lease_lock = __import__("threading").Lock()
		worker._lease_touch = 0.0

		# Fresh touch should be recent
		worker._touch_lease()
		with worker._lease_lock:
			assert time.monotonic() - worker._lease_touch < 1.0

	def test_heartbeat_thread_beats_while_fresh(self, mock_db, monkeypatch):
		worker = IDEWorker.__new__(IDEWorker)
		import threading

		worker._lease_lock = threading.Lock()
		worker._lease_touch = time.monotonic()  # fresh
		worker.update_heartbeat = MagicMock()
		monkeypatch.setattr(worker_module.time, "sleep", lambda s: (_ for _ in ()).throw(SystemExit))

		# Run one iteration — it should beat (fresh lease) then raise SystemExit
		# from the sleep to stop the loop.
		with pytest.raises(SystemExit):
			worker._heartbeat_thread_main()
		worker.update_heartbeat.assert_called_once()

	def test_heartbeat_thread_silent_when_lease_expired(self, mock_db, monkeypatch):
		worker = IDEWorker.__new__(IDEWorker)
		import threading

		worker._lease_lock = threading.Lock()
		worker._lease_touch = time.monotonic() - 10_000  # stale (> 900s lease)
		worker.update_heartbeat = MagicMock()
		monkeypatch.setattr(worker_module.time, "sleep", lambda s: (_ for _ in ()).throw(SystemExit))

		with pytest.raises(SystemExit):
			worker._heartbeat_thread_main()
		worker.update_heartbeat.assert_not_called()


class _CommitTrackingConn:
	"""Proxy around a real sqlite3.Connection that records commit order."""

	def __init__(self, conn, call_order):
		self._conn = conn
		self._call_order = call_order
		self.row_factory = conn.row_factory

	def __getattr__(self, name):
		attr = getattr(self._conn, name)
		if name == "commit":
			def _tracked(*a, **kw):
				self._call_order.append("commit")
				return attr(*a, **kw)

			return _tracked
		return attr


class TestCommitBeforePrompt:
	def test_commit_happens_before_bridge_prompt(self, mock_db):
		"""D23: the events.db transaction is committed BEFORE the bridge call so
		the write-lock is not held across a (potentially 300s) prompt."""
		worker = IDEWorker.__new__(IDEWorker)
		from red_pill.swarm.bridges import ConversationResult

		bridge = MagicMock()
		bridge.prompt.return_value = ConversationResult(
			conversation_id="conv", response="respuesta de prueba", model="opencode-go/deepseek-v4-pro"
		)
		worker._bridge_telegram = bridge
		worker._caps = MagicMock()
		worker._caps.backend.value = "opencode"
		worker._scribe_relay = MagicMock()

		call_order = []

		orig_prompt = bridge.prompt
		bridge.prompt = lambda text, **kw: (call_order.append("prompt"), orig_prompt(text, **kw))[1]

		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		tracked_conn = _CommitTrackingConn(conn, call_order)

		worker._process_via_bridge(
			combined_text="hola",
			msg_ids=[1],
			channel="telegram",
			channel_user_id="user_a",
			cursor=cursor,
			conn=tracked_conn,
		)

		assert call_order.index("commit") < call_order.index("prompt")
		conn.close()
