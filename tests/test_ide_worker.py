import json
import sqlite3
from unittest.mock import MagicMock

import pytest

import red_pill.config as cfg
from red_pill.plugins.antigravity_ide.worker import IDEWorker


@pytest.fixture
def mock_db(tmp_path, monkeypatch):
	# Create a temporary events.db for Neon-Link
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
		CREATE TABLE IF NOT EXISTS cascade_mappings (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			channel_user_id TEXT,
			cascade_id TEXT,
			title TEXT
		)
		"""
	)
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS telegram_sessions (
			channel_user_id TEXT PRIMARY KEY,
			cascade_id TEXT,
			cascade_type TEXT,
			accumulated_len INTEGER
		)
		"""
	)
	conn.commit()
	conn.close()

	# Monkeypatch DB_PATH in worker module
	import red_pill.plugins.antigravity_ide.worker as worker_module

	monkeypatch.setattr(worker_module, "DB_PATH", db_path)
	return db_path


def test_debounce_processing(mock_db, monkeypatch):
	# Configure settings: Enable debounce with 2 seconds
	monkeypatch.setattr(cfg, "REACTIVE_DEBOUNCE_ENABLED", True)
	monkeypatch.setattr(cfg, "REACTIVE_DEBOUNCE_SECONDS", 2)

	# Mock bridge and client on IDEWorker to avoid actual executions
	monkeypatch.setattr(IDEWorker, "__init__", lambda self: None)
	worker = IDEWorker()
	worker._caps = MagicMock()
	worker._caps.auto_approve = True
	worker._process_via_bridge = MagicMock()

	# Insert a pending message from 'user_a' representing "just sent"
	conn = sqlite3.connect(str(mock_db))
	conn.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, created_at) VALUES ('telegram', 'user_a', ?, datetime('now'))",
		(json.dumps({"text": "hello"}),),
	)
	conn.commit()

	# Run process_inbox() -> it should skip it because elapsed time is 0 (which is < 2s)
	worker.process_inbox()
	assert not worker._process_via_bridge.called

	# Now insert a message from 'user_b' that is older (e.g., 5 seconds ago)
	conn.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, created_at) VALUES ('telegram', 'user_b', ?, datetime('now', '-5 seconds'))",
		(json.dumps({"text": "world"}),),
	)
	conn.commit()
	conn.close()

	# Run process_inbox() -> it should process 'user_b' because its message is older than 2 seconds, but skip 'user_a'
	worker.process_inbox()
	assert worker._process_via_bridge.called
	# The first call should be for user_b
	args, kwargs = worker._process_via_bridge.call_args
	assert args[3] == "user_b"  # channel_user_id is the 4th positional argument in _process_via_bridge


def test_command_bypasses_debounce(mock_db, monkeypatch):
	# Configure settings: Enable debounce with 10 seconds
	monkeypatch.setattr(cfg, "REACTIVE_DEBOUNCE_ENABLED", True)
	monkeypatch.setattr(cfg, "REACTIVE_DEBOUNCE_SECONDS", 10)

	monkeypatch.setattr(IDEWorker, "__init__", lambda self: None)
	worker = IDEWorker()
	worker._caps = MagicMock()
	worker._caps.auto_approve = True
	worker._process_via_bridge = MagicMock()

	# Insert a command message from 'user_a' representing "just sent"
	conn = sqlite3.connect(str(mock_db))
	# We also need a row in cascade_mappings so SWITCH_CASCADE doesn't fail
	conn.execute("INSERT INTO cascade_mappings (channel_user_id, cascade_id, title) VALUES ('user_a', 'test_uuid', 'Test Tab')")
	conn.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, created_at) VALUES ('telegram', 'user_a', ?, datetime('now'))",
		(json.dumps({"command": "SWITCH_CASCADE", "index": 1}),),
	)
	conn.commit()
	conn.close()

	# Run process_inbox() -> it should NOT skip it, because it is a command message!
	worker.process_inbox()
	# Let's verify that the message status was updated from PENDING to PROCESSED
	conn = sqlite3.connect(str(mock_db))
	cursor = conn.execute("SELECT status FROM inbox WHERE channel_user_id = 'user_a'")
	status = cursor.fetchone()[0]
	assert status == "PROCESSED"
	conn.close()
