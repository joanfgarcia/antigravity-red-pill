"""
Tests for D24 (retry cap by error class) — RFC_TELEGRAM_RESILIENCE, slice mínimo
Fase 1, ítem 4.

Covers:
  - _is_bridge_timeout classifier: TimeoutExpired / "timed out" RuntimeError → True;
    spawn/network/5xx → False
  - timeout → cap 1 (second failure → DEAD)
  - transient → cap 3 (third failure → DEAD)
  - on DEAD: dead_letters row written (D12) + user notified via outbox
  - pain signal emitted when a timeout-looking failure is NOT classified as timeout
    (D24 req. operador)
"""

import json
import sqlite3
from unittest.mock import patch

import pytest

import red_pill.plugins.antigravity_ide.worker as worker_module
from red_pill.plugins.antigravity_ide.worker import IDEWorker, _is_bridge_timeout


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
		CREATE TABLE IF NOT EXISTS dead_letters (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			original_table TEXT NOT NULL,
			original_id INTEGER NOT NULL,
			channel TEXT NOT NULL,
			channel_user_id TEXT NOT NULL,
			payload TEXT NOT NULL,
			error_reason TEXT,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
		"""
	)
	conn.commit()
	conn.close()
	monkeypatch.setattr(worker_module, "DB_PATH", db_path)
	return db_path


def _insert_msg(conn, text="hola", retries=0, status="PENDING"):
	cur = conn.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, status, retries) VALUES ('telegram', 'user_a', ?, ?, ?)",
		(json.dumps({"text": text}), status, retries),
	)
	return cur.lastrowid


class TestBridgeTimeoutClassifier:
	def test_timeout_expired_is_timeout(self):
		import subprocess

		assert _is_bridge_timeout(subprocess.TimeoutExpired("opencode run", timeout=300)) is True

	def test_runtime_error_timed_out_is_timeout(self):
		assert _is_bridge_timeout(RuntimeError("opencode timed out after 300s")) is True

	def test_transient_runtime_error_not_timeout(self):
		assert _is_bridge_timeout(RuntimeError("opencode CLI not found")) is False

	def test_generic_exception_not_timeout(self):
		assert _is_bridge_timeout(ValueError("connection reset")) is False


class TestRetryCap:
	def test_timeout_cap1_dead_on_second(self, mock_db):
		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		msg_id = _insert_msg(conn, retries=0)

		# First failure (timeout) → retries=1, still PENDING
		worker._handle_retry_failure([msg_id], "telegram", "user_a", cursor, exc=RuntimeError("opencode timed out after 300s"))
		conn.commit()
		row = cursor.execute("SELECT retries, status FROM inbox WHERE id = ?", (msg_id,)).fetchone()
		assert row["retries"] == 1 and row["status"] == "PENDING"

		# Second failure (timeout) → cap 1 reached → DEAD + dead_letter + outbox
		worker._handle_retry_failure([msg_id], "telegram", "user_a", cursor, exc=RuntimeError("opencode timed out after 300s"))
		conn.commit()
		row = cursor.execute("SELECT retries, status FROM inbox WHERE id = ?", (msg_id,)).fetchone()
		assert row["status"] == "DEAD" and row["retries"] == 2

		dl = cursor.execute("SELECT * FROM dead_letters WHERE original_id = ?", (msg_id,)).fetchone()
		assert dl is not None and "timed out" in dl["error_reason"]
		outbox = cursor.execute("SELECT payload FROM outbox").fetchone()
		assert outbox is not None and "no pudo ser procesado" in json.loads(outbox["payload"])["text"]
		conn.close()

	def test_transient_cap3_dead_on_third(self, mock_db):
		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		msg_id = _insert_msg(conn, retries=0)

		for i in range(1, 4):
			worker._handle_retry_failure([msg_id], "telegram", "user_a", cursor, exc=RuntimeError(f"spawn failed attempt {i}"))
			conn.commit()
		row = cursor.execute("SELECT retries, status FROM inbox WHERE id = ?", (msg_id,)).fetchone()
		assert row["status"] == "DEAD" and row["retries"] == 3
		dl = cursor.execute("SELECT * FROM dead_letters WHERE original_id = ?", (msg_id,)).fetchone()
		assert dl is not None and "spawn failed" in dl["error_reason"]
		conn.close()

	def test_transient_survives_two_retries(self, mock_db):
		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		msg_id = _insert_msg(conn, retries=0)

		worker._handle_retry_failure([msg_id], "telegram", "user_a", cursor, exc=RuntimeError("rate limited"))
		conn.commit()
		row = cursor.execute("SELECT retries, status FROM inbox WHERE id = ?", (msg_id,)).fetchone()
		assert row["retries"] == 1 and row["status"] == "PENDING"
		conn.close()


class TestD24PainSignal:
	def test_pain_signal_emitted_when_timeout_misclassified(self, mock_db):
		"""D24 req. operador: a failure whose text says 'timeout' but is NOT
		classified as a timeout (so cap 3 would wrongly apply) must emit a typed
		pain signal."""
		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		msg_id = _insert_msg(conn)

		# A ValueError with 'timeout' in the message — classifier says NOT timeout.
		with patch.object(worker_module, "_emit_d24_pain_signal") as mock_signal:
			worker._handle_retry_failure([msg_id], "telegram", "user_a", cursor, exc=ValueError("timeout waiting for server"))
			mock_signal.assert_called_once()
		conn.close()

	def test_no_pain_signal_for_real_timeout(self, mock_db):
		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		msg_id = _insert_msg(conn)

		with patch.object(worker_module, "_emit_d24_pain_signal") as mock_signal:
			worker._handle_retry_failure([msg_id], "telegram", "user_a", cursor, exc=RuntimeError("opencode timed out after 300s"))
			mock_signal.assert_not_called()
		conn.close()

	def test_no_pain_signal_for_transient(self, mock_db):
		worker = IDEWorker.__new__(IDEWorker)
		conn = sqlite3.connect(str(mock_db))
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		msg_id = _insert_msg(conn)

		with patch.object(worker_module, "_emit_d24_pain_signal") as mock_signal:
			worker._handle_retry_failure([msg_id], "telegram", "user_a", cursor, exc=RuntimeError("spawn failed"))
			mock_signal.assert_not_called()
		conn.close()
