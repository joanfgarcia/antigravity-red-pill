import signal
import sqlite3
from unittest.mock import patch

from red_pill.metabolism.sentinel_plugins.check_sqlite import (
	SQLiteCheck,
)


@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_neon_link_db_path")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_queue_dir")
def test_audit_healthy(mock_queue_dir, mock_neon_link_path, tmp_path):
	check = SQLiteCheck()
	db_dir = tmp_path / "queue"
	db_dir.mkdir()

	neon_db = tmp_path / "events.db"
	queue_db = db_dir / "bunker_queue.db"
	inbox_db = db_dir / "minion_inbox.db"

	mock_neon_link_path.return_value = neon_db
	mock_queue_dir.return_value = db_dir

	for db in [neon_db, queue_db, inbox_db]:
		with sqlite3.connect(db) as conn:
			conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY);")
			conn.execute("PRAGMA journal_mode=WAL;")
			conn.commit()

	findings = check.audit(None)
	assert len(findings) == 0


@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_neon_link_db_path")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_queue_dir")
def test_audit_locked(mock_queue_dir, mock_neon_link_path, tmp_path):
	check = SQLiteCheck()
	db_dir = tmp_path / "queue"
	db_dir.mkdir()

	neon_db = tmp_path / "events.db"
	queue_db = db_dir / "bunker_queue.db"
	inbox_db = db_dir / "minion_inbox.db"

	mock_neon_link_path.return_value = neon_db
	mock_queue_dir.return_value = db_dir

	for db in [neon_db, queue_db, inbox_db]:
		with sqlite3.connect(db) as conn:
			conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY);")
			conn.commit()

	conn_lock = sqlite3.connect(neon_db)
	conn_lock.execute("BEGIN EXCLUSIVE;")

	findings = check.audit(None)
	conn_lock.close()

	assert len(findings) == 1
	assert findings[0].metadata["error_type"] == "locked"
	assert findings[0].metadata["db_name"] == "events.db"


@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_neon_link_db_path")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_queue_dir")
def test_audit_corrupted(mock_queue_dir, mock_neon_link_path, tmp_path):
	check = SQLiteCheck()
	db_dir = tmp_path / "queue"
	db_dir.mkdir()

	neon_db = tmp_path / "events.db"

	mock_neon_link_path.return_value = neon_db
	mock_queue_dir.return_value = db_dir

	with open(neon_db, "wb") as f:
		f.write(b"this is garbage raw bytes corrupted")

	findings = check.audit(None)
	assert len(findings) == 1
	assert findings[0].metadata["error_type"] == "corrupted"


@patch("subprocess.run")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_pid_command")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_pid_systemd_unit")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.find_processes_holding_file")
def test_heal_locked_systemd(mock_find, mock_get_unit, mock_get_cmd, mock_run, tmp_path):
	check = SQLiteCheck()
	db_file = tmp_path / "minion_inbox.db"
	with sqlite3.connect(db_file) as conn:
		conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY);")
		conn.commit()

	from red_pill.metabolism.auditor import AuditFinding

	finding = AuditFinding(
		type="amnesia",
		severity=10.0,
		message="locked",
		metadata={"db_path": str(db_file), "error_type": "locked", "db_name": "minion_inbox.db"},
	)

	mock_find.return_value = [999]
	mock_get_unit.return_value = "redpill-queue.service"
	mock_get_cmd.return_value = "python run_queue_worker.py"

	healed = check.heal(None, finding)
	assert healed is True

	mock_run.assert_called_once_with(["systemctl", "--user", "restart", "redpill-queue.service"], capture_output=True)


@patch("os.kill")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_pid_command")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_pid_systemd_unit")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.find_processes_holding_file")
def test_heal_locked_orphan(mock_find, mock_get_unit, mock_get_cmd, mock_kill, tmp_path):
	check = SQLiteCheck()
	db_file = tmp_path / "minion_inbox.db"
	with sqlite3.connect(db_file) as conn:
		conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY);")
		conn.commit()

	from red_pill.metabolism.auditor import AuditFinding

	finding = AuditFinding(
		type="amnesia",
		severity=10.0,
		message="locked",
		metadata={"db_path": str(db_file), "error_type": "locked", "db_name": "minion_inbox.db"},
	)

	mock_find.return_value = [888]
	mock_get_unit.return_value = None
	mock_get_cmd.return_value = "python -m red_pill.cli queue"

	healed = check.heal(None, finding)
	assert healed is True

	mock_kill.assert_any_call(888, signal.SIGTERM)


@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_pid_command")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.get_pid_systemd_unit")
@patch("red_pill.metabolism.sentinel_plugins.check_sqlite.find_processes_holding_file")
def test_heal_corrupted_recreate(mock_find, mock_get_unit, mock_get_cmd, tmp_path):
	check = SQLiteCheck()
	db_file = tmp_path / "minion_inbox.db"
	with open(db_file, "wb") as f:
		f.write(b"corrupt header")

	from red_pill.metabolism.auditor import AuditFinding

	finding = AuditFinding(
		type="amnesia",
		severity=10.0,
		message="corrupted",
		metadata={"db_path": str(db_file), "error_type": "corrupted", "db_name": "minion_inbox.db"},
	)

	mock_find.return_value = []
	healed = check.heal(None, finding)
	assert healed is True

	assert (tmp_path / "minion_inbox.db.corrupted_bak").exists()
	assert db_file.exists()
	with sqlite3.connect(db_file) as conn:
		res = conn.execute("PRAGMA integrity_check").fetchone()
		assert res[0] == "ok"
