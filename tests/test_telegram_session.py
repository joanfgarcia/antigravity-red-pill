import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from red_pill.plugins.antigravity_ide.telegram_session import TelegramSessionManager
from red_pill.plugins.antigravity_ide.worker import IDEWorker


@pytest.fixture
def mock_telegram_env(tmp_path, monkeypatch):
	# Isolate XDG directories to tmp_path
	data_dir = tmp_path / "data"
	config_dir = tmp_path / "config"
	state_dir = tmp_path / "state"
	cache_dir = tmp_path / "cache"

	monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
	monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
	monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))
	monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
	monkeypatch.setenv("IA_DIR", str(tmp_path))

	# Re-import get_data_dir / get_staging_dir to check if paths are correct
	from red_pill.core.paths import get_data_dir, get_staging_dir

	assert str(get_data_dir()).startswith(str(data_dir))
	assert str(get_staging_dir()).startswith(str(cache_dir))

	# Setup events.db for worker commands
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

	import red_pill.plugins.antigravity_ide.worker as worker_module

	monkeypatch.setattr(worker_module, "DB_PATH", db_path)

	return tmp_path, db_path


def test_create_session(mock_telegram_env):
	tmp_path, _ = mock_telegram_env
	tsm = TelegramSessionManager()

	session = tsm.create_session("user123", "Test Session")
	assert session["channel_user_id"] == "user123"
	assert session["status"] == "active"
	assert session["summary"]["summary"] == "Test Session"
	assert len(session["steps"]) == 0

	# Verify file written to disk
	sess_path = tsm.conv_dir / f"{session['id']}.json"
	assert sess_path.exists()
	with open(sess_path, "r", encoding="utf-8") as f:
		saved = json.load(f)
	assert saved["id"] == session["id"]


def test_append_message_and_prompt(mock_telegram_env):
	mock_telegram_env
	tsm = TelegramSessionManager()
	session = tsm.create_session("user123")
	session_id = session["id"]

	tsm.append_message(session_id, "user", "Hola, Aleth")
	tsm.append_message(session_id, "assistant", "Hola, Joan. ¿En qué trabajamos hoy?")

	# Reload from disk
	saved = tsm.get_session(session_id)
	assert len(saved["steps"]) == 2
	assert saved["steps"][0]["intent"] == "USER"
	assert saved["steps"][0]["message"]["text"] == "Hola, Aleth"
	assert saved["steps"][1]["intent"] == "ASSISTANT"
	assert saved["steps"][1]["message"]["text"] == "Hola, Joan. ¿En qué trabajamos hoy?"

	prompt = tsm.get_history_prompt(saved)
	assert prompt == "USER: Hola, Aleth\n\nASSISTANT: Hola, Joan. ¿En qué trabajamos hoy?"


def test_copy_to_staging(mock_telegram_env):
	mock_telegram_env
	tsm = TelegramSessionManager()
	session = tsm.create_session("user123")
	session_id = session["id"]

	tsm.append_message(session_id, "user", "Test message")

	success = tsm.copy_to_staging(session_id)
	assert success

	staging_path = tsm.staging_dir / f"{session_id}.json"
	assert staging_path.exists()
	with open(staging_path, "r", encoding="utf-8") as f:
		staged = json.load(f)
	assert staged["id"] == session_id
	assert staged["steps"][0]["message"]["text"] == "Test message"


def test_mark_for_deletion(mock_telegram_env):
	mock_telegram_env
	tsm = TelegramSessionManager()
	session = tsm.create_session("user123")
	session_id = session["id"]

	success = tsm.mark_for_deletion(session_id)
	assert success

	# Verify status is updated
	saved = tsm.get_session(session_id)
	assert saved["status"] == "pending_purge"

	# Verify it copied to staging
	staging_path = tsm.staging_dir / f"{session_id}.json"
	assert staging_path.exists()


def test_trigger_compaction(mock_telegram_env):
	mock_telegram_env
	tsm = TelegramSessionManager()
	session = tsm.create_session("user123")
	session_id = session["id"]

	# Add 16 messages (8 exchanges)
	for i in range(8):
		tsm.append_message(session_id, "user", f"message {i}")
		tsm.append_message(session_id, "assistant", f"reply {i}")

	# Mock AgyBridge
	mock_bridge = MagicMock()
	mock_res = MagicMock()
	mock_res.ok = True
	mock_res.response = "Resumen consolidado de tareas y progreso."
	mock_bridge.prompt.return_value = mock_res

	# Trigger compaction
	new_id = tsm.trigger_compaction(session_id, mock_bridge)
	assert new_id is not None
	assert new_id != session_id

	# Verify old session marked pending_purge
	old_session = tsm.get_session(session_id)
	assert old_session["status"] == "pending_purge"
	assert (tsm.staging_dir / f"{session_id}.json").exists()

	# Verify new session created with summary
	new_session = tsm.get_session(new_id)
	assert new_session["channel_user_id"] == "user123"
	assert len(new_session["steps"]) == 2
	assert "Resumen de la sesión anterior" in new_session["steps"][0]["message"]["text"]
	assert "Resumen consolidado" in new_session["steps"][0]["message"]["text"]


@patch("red_pill.memory.MemoryManager")
def test_run_janitor_sweep(mock_mm_class, mock_telegram_env):
	mock_telegram_env
	tsm = TelegramSessionManager()

	# Create two sessions marked for deletion
	sess_archived = tsm.create_session("user123")
	sess_kept = tsm.create_session("user123")

	tsm.mark_for_deletion(sess_archived["id"])
	tsm.mark_for_deletion(sess_kept["id"])

	# Mock MemoryManager and client scroll behavior
	mock_mm = MagicMock()
	mock_client = MagicMock()
	mock_mm.client = mock_client
	mock_mm_class.return_value = mock_mm

	# Custom scroll mock to return points only for sess_archived
	def mock_scroll(collection_name, scroll_filter, limit):
		# Extract target session_id from filter
		try:
			conditions = scroll_filter.must
			target_val = conditions[0].match.value
			if target_val == sess_archived["id"]:
				return ([MagicMock()], None)
		except Exception:
			pass
		return ([], None)

	mock_client.scroll.side_effect = mock_scroll

	purged = tsm.run_janitor_sweep()
	assert purged == 1

	# Archived session file should be unlinked
	assert not tsm._get_path(sess_archived["id"]).exists()
	# Non-archived session file should still exist
	assert tsm._get_path(sess_kept["id"]).exists()


def test_worker_delete_command_active(mock_telegram_env, monkeypatch):
	tmp_path, db_path = mock_telegram_env
	tsm = TelegramSessionManager()

	# Setup active telegram session in DB and disk
	sess = tsm.create_session("user_test", "Interactive Session")
	conn = sqlite3.connect(str(db_path))
	conn.execute(
		"INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES ('user_test', ?, 'local_session')", (sess["id"],)
	)
	conn.commit()
	conn.close()

	# Instantiate worker
	monkeypatch.setattr(IDEWorker, "__init__", lambda self: None)
	worker = IDEWorker()
	worker._caps = MagicMock()
	worker._caps.auto_approve = True

	# Ingest /delete command into inbox
	conn = sqlite3.connect(str(db_path))
	conn.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, created_at) VALUES ('telegram', 'user_test', ?, datetime('now', '-5 seconds'))",
		(json.dumps({"text": "/delete"}),),
	)
	conn.commit()
	conn.close()

	worker.process_inbox()

	# Assert session marked pending_purge on disk
	updated_sess = tsm.get_session(sess["id"])
	assert updated_sess["status"] == "pending_purge"

	# Assert active session cleared from DB
	conn = sqlite3.connect(str(db_path))
	cursor = conn.execute("SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = 'user_test'")
	row = cursor.fetchone()
	assert row is None

	# Assert response outbox message is generated
	cursor = conn.execute("SELECT payload FROM outbox WHERE channel_user_id = 'user_test'")
	outbox_msg = json.loads(cursor.fetchone()[0])
	assert "marcada para eliminación" in outbox_msg["text"]
	conn.close()


def test_worker_delete_command_by_index(mock_telegram_env, monkeypatch):
	tmp_path, db_path = mock_telegram_env
	tsm = TelegramSessionManager()

	# Create two sessions
	sess1 = tsm.create_session("user_test", "First session")
	sess2 = tsm.create_session("user_test", "Second session")

	# Populate cascade_mappings in DB
	conn = sqlite3.connect(str(db_path))
	conn.execute("INSERT INTO cascade_mappings (channel_user_id, cascade_id, title) VALUES ('user_test', ?, 'First session')", (sess1["id"],))
	conn.execute("INSERT INTO cascade_mappings (channel_user_id, cascade_id, title) VALUES ('user_test', ?, 'Second session')", (sess2["id"],))
	conn.commit()
	conn.close()

	monkeypatch.setattr(IDEWorker, "__init__", lambda self: None)
	worker = IDEWorker()
	worker._caps = MagicMock()
	worker._caps.auto_approve = True

	# Ingest /delete 2 command into inbox (second mapping)
	conn = sqlite3.connect(str(db_path))
	conn.execute(
		"INSERT INTO inbox (channel, channel_user_id, payload, created_at) VALUES ('telegram', 'user_test', ?, datetime('now', '-5 seconds'))",
		(json.dumps({"text": "/delete 2"}),),
	)
	conn.commit()
	conn.close()

	worker.process_inbox()

	# Assert second session marked pending_purge on disk, but first is still active
	updated_sess2 = tsm.get_session(sess2["id"])
	assert updated_sess2["status"] == "pending_purge"

	updated_sess1 = tsm.get_session(sess1["id"])
	assert updated_sess1["status"] == "active"

	# Assert output matches deletion message
	conn = sqlite3.connect(str(db_path))
	cursor = conn.execute("SELECT payload FROM outbox WHERE channel_user_id = 'user_test'")
	outbox_msg = json.loads(cursor.fetchone()[0])
	assert "Second session" in outbox_msg["text"]
	conn.close()
