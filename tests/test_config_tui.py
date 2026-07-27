"""
Unit tests for the TUI Dashboard & Configuration Manager (config_tui.py).
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("prompt_toolkit")

from red_pill.config_tui import (
	EnvConfig,
	build_tui_app,
	fetch_hardware_telemetry,
	fetch_qdrant_counts,
	fetch_sqlite_queues,
	fetch_systemd_timers,
	fetch_systemd_vitals,
)


class TestEnvConfig:
	def test_load_and_get(self, tmp_path):
		env_file = tmp_path / ".env"
		env_file.write_text("# Core settings\nKEY_ONE=val1\n# another comment\nKEY_TWO=val2\n", encoding="utf-8")

		config = EnvConfig(env_file)
		assert config.get("KEY_ONE") == "val1"
		assert config.get("KEY_TWO") == "val2"
		assert config.get("NONEXISTENT", "default") == "default"

	def test_set_and_save(self, tmp_path):
		env_file = tmp_path / ".env"
		env_file.write_text("# Core settings\nKEY_ONE=val1\n# another comment\nKEY_TWO=val2\n", encoding="utf-8")

		config = EnvConfig(env_file)
		config.set("KEY_ONE", "new_val")
		config.set("KEY_THREE", "val3")
		config.save()

		# Check backup exists
		bak_file = tmp_path / ".env.bak"
		assert bak_file.exists()
		assert "KEY_ONE=val1" in bak_file.read_text(encoding="utf-8")

		# Check saved content preserves comments and updates key
		saved_content = env_file.read_text(encoding="utf-8")
		assert "# Core settings" in saved_content
		assert "KEY_ONE=new_val" in saved_content
		assert "# another comment" in saved_content
		assert "KEY_TWO=val2" in saved_content
		assert "KEY_THREE=val3" in saved_content


class TestFetchVitals:
	@patch("subprocess.run")
	def test_systemd_vitals_failed(self, mock_run):
		mock_run.return_value = MagicMock(stdout="failed-service.service failed failed\n", stderr="", returncode=0)
		vitals = fetch_systemd_vitals()
		assert "Systemd Failures:" in vitals
		assert "failed-service.service" in vitals

	@patch("subprocess.run")
	def test_systemd_vitals_ok(self, mock_run):
		mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
		vitals = fetch_systemd_vitals()
		assert "Systemd Services: OK" in vitals

	@patch("subprocess.run")
	def test_systemd_vitals_error(self, mock_run):
		mock_run.side_effect = Exception("Systemd offline")
		vitals = fetch_systemd_vitals()
		assert "Systemd Check Failed: Systemd offline" in vitals


class TestFetchTimers:
	@patch("subprocess.run")
	def test_systemd_timers_active(self, mock_run):
		mock_run.return_value = MagicMock(
			stdout="redpill-sleep.timer active active\nredpill-awake.timer inactive inactive\n", stderr="", returncode=0
		)
		timers = fetch_systemd_timers()
		assert "Active Timers:" in timers
		assert "redpill-sleep.timer: active" in timers
		assert "redpill-awake.timer: inactive" in timers

	@patch("subprocess.run")
	def test_systemd_timers_empty(self, mock_run):
		mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)
		timers = fetch_systemd_timers()
		assert "No active redpill-*.timer units found." in timers


class TestFetchQdrant:
	@patch("qdrant_client.QdrantClient")
	def test_qdrant_counts_connected(self, mock_client_cls):
		mock_client = MagicMock()
		mock_client_cls.return_value = mock_client
		mock_client.count.side_effect = [MagicMock(count=42), MagicMock(count=100), Exception("missing")]

		out = fetch_qdrant_counts()
		assert "Qdrant Client: Connected" in out
		assert "work_memories: 42 points" in out
		assert "social_memories: 100 points" in out
		assert "system_signals: Collection missing/unreachable" in out


class TestFetchSqliteQueues:
	def test_sqlite_db_missing(self, tmp_path):
		with patch("red_pill.config_tui.get_neon_link_db_path") as mock_db_path:
			mock_db_path.return_value = tmp_path / "nonexistent.db"
			res = fetch_sqlite_queues()
			assert "SQLite Database not found" in res

	def test_sqlite_db_query(self, tmp_path):
		db_file = tmp_path / "events.db"
		conn = sqlite3.connect(str(db_file))
		cursor = conn.cursor()
		cursor.execute("CREATE TABLE inbox (status TEXT)")
		cursor.execute("CREATE TABLE outbox (status TEXT)")
		cursor.execute("CREATE TABLE dead_letters (id INTEGER)")

		# Insert mock data
		cursor.execute("INSERT INTO inbox VALUES ('PENDING')")
		cursor.execute("INSERT INTO inbox VALUES ('PENDING')")
		cursor.execute("INSERT INTO inbox VALUES ('PROCESSING')")
		cursor.execute("INSERT INTO outbox VALUES ('PENDING')")
		cursor.execute("INSERT INTO dead_letters VALUES (1)")
		conn.commit()
		conn.close()

		with patch("red_pill.config_tui.get_neon_link_db_path") as mock_db_path:
			mock_db_path.return_value = db_file
			res = fetch_sqlite_queues()
			assert "Inbox Queue: PENDING: 2, PROCESSING: 1" in res
			assert "Outbox Queue: PENDING: 1" in res
			assert "Dead Letters: 1 messages" in res


class TestHardwareTelemetry:
	@patch("psutil.cpu_percent")
	@patch("shutil.which")
	@patch("subprocess.run")
	def test_hardware_nvidia(self, mock_run, mock_which, mock_cpu):
		mock_cpu.return_value = 25.5
		mock_which.return_value = "/usr/bin/nvidia-smi"
		mock_run.return_value = MagicMock(stdout=" 1024, 8192 \n", stderr="", returncode=0)

		res = fetch_hardware_telemetry()
		assert "CPU Utilization: 25.5%" in res
		assert "GPU VRAM Used: 1024 MB / 8192 MB" in res


class TestBuildTui:
	def test_build_app_structure(self, tmp_path):
		env_file = tmp_path / ".env"
		env_file.write_text("QDRANT_HOST=myhost\nQDRANT_PORT=7777\nIDE_BACKEND=claude\nAUTONOMOUS_AGY_ENABLED=True\n", encoding="utf-8")

		with patch("red_pill.config_tui.get_config_dir") as mock_conf_dir:
			mock_conf_dir.return_value = tmp_path
			app = build_tui_app()
			assert app is not None
			# Test key bindings exist
			assert app.key_bindings is not None
