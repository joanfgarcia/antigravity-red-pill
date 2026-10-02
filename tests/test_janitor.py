import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from red_pill.swarm.agents.janitor import JanitorMinion, discover_plugins
from red_pill.swarm.agents.janitor_plugins.log_rotation import LogRotationPlugin


@pytest.fixture
def temp_dir():
	with tempfile.TemporaryDirectory() as tmpdir:
		yield Path(tmpdir)


def test_janitor_log_rotation_and_cleanup(temp_dir):
	# Create a mock active log file with content
	log_file = temp_dir / "error.log"
	log_file.write_text("some error log content here")
	assert log_file.exists()

	# Create some existing backups
	backup1 = temp_dir / "error.log.1"
	backup1.write_text("old content 1")
	backup2 = temp_dir / "error.log.2"
	backup2.write_text("old content 2")

	# Make backup2 old (e.g. 40 days old) to test cleanup
	old_time = (datetime.now() - timedelta(days=40)).timestamp()
	os.utime(backup2, (old_time, old_time))

	# Initialize janitor
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())

	# Test copytruncate rotation
	assert log_file.stat().st_size > 0
	LogRotationPlugin()._rotate_file_copytruncate(janitor, log_file)

	# Verify active log is truncated to size 0
	assert log_file.exists()
	assert log_file.stat().st_size == 0

	# Verify backup 1 now has the active content
	rotated_1 = temp_dir / "error.log.1"
	assert rotated_1.exists()
	assert rotated_1.read_text() == "some error log content here"

	# Verify backup 2 now has the shifted content from old backup 1
	rotated_2 = temp_dir / "error.log.2"
	assert rotated_2.exists()
	assert rotated_2.read_text() == "old content 1"

	# Test cleanup of old logs
	# Set mtime of rotated_2 to 40 days ago to trigger expiration
	os.utime(rotated_2, (old_time, old_time))

	purged = LogRotationPlugin()._cleanup_old_rotated_logs(janitor, temp_dir, "error.log", days=30)
	assert purged == 2
	assert not rotated_2.exists()
	assert rotated_1.exists()


def test_awakening_logs_purges_older_than_ttl(temp_dir, monkeypatch):
	"""El plugin borra los logs de despertar > days_to_keep y respeta el resto."""
	from red_pill.swarm.agents.janitor_plugins import awakening_logs as mod

	monkeypatch.setattr(mod, "get_awakening_dir", lambda create=True: temp_dir)

	old = temp_dir / f"{(datetime.now() - timedelta(days=40)).strftime('%Y%m%d')}_0000.log"
	old.write_text("old")
	recent = temp_dir / f"{datetime.now().strftime('%Y%m%d')}_1200.log"
	recent.write_text("recent")
	# Fichero no conforme: nunca se toca, aunque sea viejo (la edad sale del nombre)
	stray = temp_dir / "stray.log"
	stray.write_text("x")
	ancient = (datetime.now() - timedelta(days=400)).timestamp()
	os.utime(stray, (ancient, ancient))
	# Subcarpetas y docs del buzón: nunca se tocan
	notes = temp_dir / "notes"
	notes.mkdir()
	(notes / "hola.md").write_text("nota")

	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())

	cfg = {"plugins": {"awakening_logs": {"days_to_keep": 30}}}
	result = asyncio.run(mod.AwakeningLogsPlugin().execute(janitor, cfg))

	assert result["awakening_logs_purged"] == 1
	assert not old.exists()
	assert recent.exists()
	assert stray.exists()
	assert (notes / "hola.md").exists()


def test_awakening_logs_missing_dir_is_safe(tmp_path, monkeypatch):
	"""Sin directorio de awakening, el plugin no falla ni borra nada."""
	from red_pill.swarm.agents.janitor_plugins import awakening_logs as mod

	monkeypatch.setattr(mod, "get_awakening_dir", lambda create=True: tmp_path / "does-not-exist")
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())

	res = asyncio.run(mod.AwakeningLogsPlugin().execute(janitor, {}))
	assert res["awakening_logs_purged"] == 0


def test_load_janitor_config_reads_operator_yaml(tmp_path, monkeypatch):
	"""El minion carga ${CONFIG_DIR}/janitor.yaml (antes quedaba inerte)."""
	from red_pill.swarm.agents import janitor as mod

	(tmp_path / "janitor.yaml").write_text("plugins:\n  awakening_logs:\n    days_to_keep: 45\n")
	monkeypatch.setattr(mod, "get_config_dir", lambda: tmp_path)

	cfg = mod._load_janitor_config()
	assert cfg["plugins"]["awakening_logs"]["days_to_keep"] == 45


def test_janitor_discovers_all_plugins():
	"""El orquestador agnóstico descubre los plugins del paquete janitor_plugins."""
	names = {p.name for p in discover_plugins()}
	assert {
		"events_db_purge",
		"log_rotation",
		"orphaned_parents_sweep",
		"queue_hygiene",
		"scratch_purge",
	} <= names


def test_awakening_logs_never_creates_the_desk(tmp_path, monkeypatch):
	"""Regresión: resolver el dir de awakening creaba un desk fantasma."""
	from red_pill.swarm.agents.janitor_plugins import awakening_logs as mod

	ghost = tmp_path / "Agent_Core"
	monkeypatch.setenv("AGENT_CORE_DIR", str(ghost))
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())

	res = asyncio.run(mod.AwakeningLogsPlugin().execute(janitor, {}))

	assert res["awakening_logs_purged"] == 0
	assert not ghost.exists()


def test_agent_core_root_reads_registry_without_env(tmp_path, monkeypatch):
	"""Sin env (servicios systemd), la fuente es el registro, no el hermano Agent_Core."""
	from red_pill.core import paths, workspaces

	monkeypatch.delenv("AGENT_CORE_DIR", raising=False)
	monkeypatch.setattr(workspaces, "agent_core_dir", lambda: tmp_path / "desk")
	assert paths.get_agent_core_root() == tmp_path / "desk"

	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path / "env-desk"))
	assert paths.get_agent_core_root() == tmp_path / "env-desk"
