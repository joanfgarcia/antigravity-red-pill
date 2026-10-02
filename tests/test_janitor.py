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


def test_awakening_logs_cutoff_compares_dates(temp_dir, monkeypatch):
	"""TTL por FECHA: con 30 días se conserva el log de hace 30 días y cae el de hace 31
	(antes la medianoche del nombre vs `now - 30d` borraba logs de 29-30 días)."""
	from red_pill.swarm.agents.janitor_plugins import awakening_logs as mod

	monkeypatch.setattr(mod, "get_awakening_dir", lambda create=True: temp_dir)
	today = datetime.now().date()
	keep = temp_dir / f"{(today - timedelta(days=30)).strftime('%Y%m%d')}_0000.log"
	drop = temp_dir / f"{(today - timedelta(days=31)).strftime('%Y%m%d')}_2359.log"
	keep.write_text("k")
	drop.write_text("d")
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())

	res = asyncio.run(mod.AwakeningLogsPlugin().execute(janitor, {"plugins": {"awakening_logs": {"days_to_keep": 30}}}))

	assert res["awakening_logs_purged"] == 1
	assert keep.exists() and not drop.exists()


def _git(repo, *args):
	import subprocess

	return subprocess.run(
		["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
		capture_output=True,
		text=True,
		check=True,
	).stdout


def test_awakening_logs_stages_deletions_in_desk_repo(tmp_path, monkeypatch):
	"""El desk es un repo git: la baja de los logs purgados queda PREPARADA (`D `),
	no como `D` sin preparar; un log nunca commiteado se borra sin error."""
	from red_pill.swarm.agents.janitor_plugins import awakening_logs as mod

	desk = tmp_path / "desk"
	awk = desk / "awakening"
	awk.mkdir(parents=True)
	_git(desk, "init", "-q")
	old_day = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
	tracked = awk / f"{old_day}_0300.log"
	tracked.write_text("t")
	fresh = awk / f"{datetime.now().strftime('%Y%m%d')}_0300.log"
	fresh.write_text("f")
	_git(desk, "add", "-A")
	_git(desk, "commit", "-q", "-m", "logs")
	untracked = awk / f"{old_day}_0400.log"
	untracked.write_text("u")
	other = desk / "notes.md"  # cambio ajeno sin preparar: no se toca
	other.write_text("x")

	monkeypatch.setattr(mod, "get_awakening_dir", lambda create=True: awk)
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())

	res = asyncio.run(mod.AwakeningLogsPlugin().execute(janitor, {}))

	assert res["awakening_logs_purged"] == 2
	assert not tracked.exists() and not untracked.exists() and fresh.exists()
	status = _git(desk, "status", "--porcelain").splitlines()
	assert f"D  awakening/{tracked.name}" in status
	assert "?? notes.md" in status
	assert not any(untracked.name in line for line in status)


def test_awakening_logs_git_failure_never_raises(temp_dir, monkeypatch):
	"""Si git falla (o no existe), el borrado se mantiene y el plugin no lanza."""
	from red_pill.swarm.agents.janitor_plugins import awakening_logs as mod

	monkeypatch.setattr(mod, "get_awakening_dir", lambda create=True: temp_dir)

	def _boom(*a, **k):
		raise FileNotFoundError("git")

	monkeypatch.setattr(mod.subprocess, "run", _boom)
	old = temp_dir / f"{(datetime.now() - timedelta(days=90)).strftime('%Y%m%d')}_0000.log"
	old.write_text("x")
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())

	res = asyncio.run(mod.AwakeningLogsPlugin().execute(janitor, {}))
	assert res["awakening_logs_purged"] == 1
	assert not old.exists()


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


def test_normalize_plugins_tolerates_bad_yaml(caplog):
	"""`plugins` como lista o valores escalares no tumban el merge: se ignoran con warning."""
	from red_pill.swarm.agents import janitor as mod

	assert mod._normalize_plugins(["events_db_purge"], "janitor.yaml") == {}
	assert mod._normalize_plugins(None, "janitor.yaml") == {}
	out = mod._normalize_plugins(
		{"a": {"days_to_keep": 3}, "b": False, "c": None, "d": 7, "e": "texto", "f": [1]},
		"janitor.yaml",
	)
	assert out == {"a": {"days_to_keep": 3}, "b": {"enabled": False}, "c": {}}
	assert "'d'" in caplog.text and "'e'" in caplog.text and "'f'" in caplog.text


def test_janitor_execute_survives_malformed_config(tmp_path, monkeypatch):
	"""YAML con `plugins` escalares + caller con config inválida → el barrido corre y el
	atajo `nombre: false` sigue desactivando el plugin."""
	from red_pill.swarm.agents import janitor as mod
	from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

	seen = {}

	class _Probe(JanitorPlugin):
		@property
		def name(self):
			return "probe"

		async def execute(self, janitor, config_dict, **kwargs):
			seen["cfg"] = config_dict["plugins"].get("probe")
			return {}

	class _Off(_Probe):
		@property
		def name(self):
			return "apagado"

	(tmp_path / "janitor.yaml").write_text("plugins:\n  probe: true\n  apagado: false\n  broken: 3\n")
	monkeypatch.setattr(mod, "get_config_dir", lambda: tmp_path)
	monkeypatch.setattr(mod, "discover_plugins", lambda: [_Probe(), _Off()])

	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())
	res = asyncio.run(janitor.execute("sweep", config={"plugins": {"probe": {"ttl_h": 1}, "bad": [1, 2]}}))

	assert res["status"] == "success"
	assert res["plugins_run"] == 1  # `apagado: false` desactiva; `broken`/`bad` se ignoran
	assert seen["cfg"] == {"enabled": True, "ttl_h": 1}


def test_janitor_execute_plugins_list_in_yaml(tmp_path, monkeypatch):
	from red_pill.swarm.agents import janitor as mod

	(tmp_path / "janitor.yaml").write_text("plugins:\n  - events_db_purge\n")
	monkeypatch.setattr(mod, "get_config_dir", lambda: tmp_path)
	monkeypatch.setattr(mod, "discover_plugins", lambda: [])
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())
	res = asyncio.run(janitor.execute("sweep", days_to_keep=3))
	assert res["status"] == "success"
