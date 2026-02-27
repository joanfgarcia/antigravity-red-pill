import argparse
import os
import sys
from unittest.mock import patch

from red_pill.cli import get_collection, handle_mode, main

# Ensure scripts and other root modules are importable
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_path not in sys.path:
	sys.path.insert(0, root_path)


def test_get_collection():
	assert get_collection("social") == "social_memories"
	assert get_collection("work") == "work_memories"
	assert get_collection("unknown") == "directive_memories"


def test_handle_mode_unit():
	"""Unit test for mode switching logic."""
	args = argparse.Namespace(skin="760")
	with patch("red_pill.cli.switch_skin", return_value="Switched to 760") as mock_switch:
		handle_mode(args)
		mock_switch.assert_called_once_with("760")


@patch("red_pill.cli.MemoryManager")
@patch("red_pill.cli.get_telemetry_report", return_value="Telemetry OK")
def test_cli_main_status(mock_telemetry, mock_mgr):
	"""Test 'red-pill status'."""
	with patch("sys.argv", ["red-pill", "status"]):
		main()
		mock_telemetry.assert_called_once()


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_backup(mock_soul):
	"""Test 'red-pill soul backup'."""
	with patch("sys.argv", ["red-pill", "soul", "backup"]):
		main()
		mock_soul.return_value.full_backup.assert_called_once()


@patch("red_pill.cli.MemoryManager")
def test_cli_main_search(mock_mgr):
	"""Test 'red-pill search work test'."""
	mock_mgr.return_value.search_and_reinforce.return_value = []
	with patch("sys.argv", ["red-pill", "search", "work", "testing query"]):
		main()
		mock_mgr.return_value.search_and_reinforce.assert_called_once()


@patch("red_pill.cli.MemoryManager")
def test_cli_main_sanitize(mock_mgr):
	"""Test 'red-pill sanitize work'."""
	mock_mgr.return_value.sanitize.return_value = {"duplicates_found": 0, "migrated_records": 0}
	with patch("sys.argv", ["red-pill", "sanitize", "work"]):
		main()
		mock_mgr.return_value.sanitize.assert_called_once_with("work_memories", dry_run=False)


@patch("red_pill.cli.MemoryManager")
def test_cli_main_add(mock_mgr):
	"""Test 'red-pill add work sample'."""
	with patch("sys.argv", ["red-pill", "add", "work", "sample content"]):
		main()
		mock_mgr.return_value.add_memory.assert_called_once()


@patch("red_pill.cli.MemoryManager")
def test_cli_main_erode(mock_mgr):
	"""Test 'red-pill erode work'."""
	with patch("sys.argv", ["red-pill", "erode", "work"]):
		main()
		mock_mgr.return_value.apply_erosion.assert_called_once()


@patch("red_pill.cli.MemoryManager")
def test_cli_main_edit(mock_mgr):
	"""Test 'red-pill edit work <id> --color purple'."""
	with patch("sys.argv", ["red-pill", "edit", "work", "550e8400-e29b-41d4-a716-446655440000", "--color", "purple"]):
		main()
		mock_mgr.return_value.update_memory.assert_called_once()


@patch("red_pill.cli.SoulManager")
@patch("red_pill.cli.get_current_sync_state")
def test_cli_main_soul_sync(mock_sync, mock_soul):
	"""Test 'red-pill soul sync'."""
	mock_sync.return_value = {"mood": "joy", "directive": "be happy"}
	with patch("sys.argv", ["red-pill", "soul", "sync"]):
		main()
		mock_sync.assert_called_once()


@patch("red_pill.cli.GruOrchestrator")
@patch("red_pill.cli.SmithMinion")
@patch("asyncio.run")
def test_cli_main_swarm_audit(mock_run, mock_smith, mock_gru):
	"""Test 'red-pill swarm audit'."""
	with patch("sys.argv", ["red-pill", "swarm", "audit"]):
		main()
		mock_run.assert_called()


@patch("red_pill.cli.MemoryManager")
def test_cli_main_diagnostic(mock_mgr):
	"""Test 'red-pill diag work'."""
	with patch("sys.argv", ["red-pill", "diag", "work"]):
		main()
		assert mock_mgr.called


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_vault(mock_soul):
	"""Test 'red-pill soul vault'."""
	mock_soul.return_value.vault.enabled = True
	mock_soul.return_value.vault.list_backups.return_value = [{"name": "bkp", "id": "1", "createdTime": "today"}]
	with patch("sys.argv", ["red-pill", "soul", "vault"]):
		main()
		mock_soul.return_value.vault.list_backups.assert_called_once()


@patch("red_pill.cli.MemoryManager")
@patch("red_pill.cli.seed_project")
def test_cli_main_seed(mock_seed, mock_mgr):
	"""Test 'red-pill seed'."""
	with patch("sys.argv", ["red-pill", "seed"]):
		main()
		mock_seed.assert_called_once()


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_rotate(mock_soul):
	"""Test 'red-pill soul rotate'."""
	# The 'rotate' function is imported inside main, so we patch the module it comes from
	with patch("scripts.rotate_keys.rotate") as mock_rotate:
		with patch("sys.argv", ["red-pill", "soul", "rotate"]):
			main()
			mock_rotate.assert_called_once()


@patch("red_pill.memory_daemon.MemoryDaemon")
@patch("red_pill.cli.signal.signal")
def test_handle_daemon_success(mock_signal, mock_daemon_cls):
	"""Test handle_daemon function success path."""
	mock_daemon = mock_daemon_cls.return_value
	with patch("sys.exit"):
		# Note: handle_daemon has a local import
		from red_pill.cli import handle_daemon

		handle_daemon()
		mock_daemon.start.assert_called_once()
		assert mock_signal.called


@patch("red_pill.memory_daemon.MemoryDaemon")
def test_handle_daemon_failure(mock_daemon_cls):
	"""Test handle_daemon function failure path."""
	mock_daemon_cls.side_effect = Exception("Failed to start")
	with patch("sys.exit") as mock_exit:
		from red_pill.cli import handle_daemon

		handle_daemon()
		mock_exit.assert_called_with(1)


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_export(mock_soul):
	"""Test 'red-pill soul export'."""
	with patch("sys.argv", ["red-pill", "soul", "export"]):
		main()
		mock_soul.return_value.export_soul.assert_called_once()


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_restore(mock_soul):
	"""Test 'red-pill soul restore'."""
	with patch("sys.argv", ["red-pill", "soul", "restore", "/tmp/bkp", "--commit"]):
		main()
		mock_soul.return_value.restore_soul.assert_called_once_with("/tmp/bkp", commit=True)
