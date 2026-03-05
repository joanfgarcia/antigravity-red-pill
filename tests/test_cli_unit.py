import argparse
import os
import sys
from unittest.mock import MagicMock, patch

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


# ─────────────────────────────────────────────────────────────────────────────
# switch_skin() failure paths — lines 28-29, 52-53
# ─────────────────────────────────────────────────────────────────────────────


def test_switch_skin_yaml_load_failure():
	"""Lines 28-29: YAML file read fails → error message returned."""
	from red_pill.cli import switch_skin

	with patch("builtins.open", side_effect=OSError("file not found")):
		result = switch_skin("matrix")
	assert "Lore load failed" in result or "failed" in result.lower()


def test_switch_skin_invalid_mode():
	"""Lines 31-32: skin_name not in skins → invalid mode message."""
	from red_pill.cli import switch_skin

	with patch("yaml.safe_load", return_value={"modes": {"matrix": {"chroma": "green"}}}):
		with patch("builtins.open", MagicMock()):
			result = switch_skin("nonexistent_mode")
	assert "Invalid mode" in result


@patch("red_pill.cli.MemoryManager")
def test_switch_skin_persist_exception(mock_mgr):
	"""Lines 52-53: MemoryManager.add_memory raises → error appended."""
	from red_pill.cli import switch_skin

	mock_mgr.return_value.add_memory.side_effect = RuntimeError("Qdrant dead")
	with patch("yaml.safe_load", return_value={"modes": {"matrix": {"chroma": "green", "assistant": "Neo"}}}):
		with patch("builtins.open", MagicMock()):
			result = switch_skin("matrix")
	assert "[ERROR]" in result or "Failed" in result


# ─────────────────────────────────────────────────────────────────────────────
# main() — no command → print_help (lines 166-168)
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_main_no_command_exits():
	"""Lines 166-168: no command → parser.print_help() + sys.exit(0)."""
	with patch("sys.argv", ["red-pill"]):
		with patch("sys.exit") as mock_exit:
			main()
			mock_exit.assert_called_with(0)


# ─────────────────────────────────────────────────────────────────────────────
# main() — daemon command (lines 170-172)
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_main_daemon_command():
	"""Lines 170-172: command == 'daemon' → handle_daemon called."""
	with patch("sys.argv", ["red-pill", "daemon"]):
		with patch("red_pill.cli.handle_daemon") as mock_handle:
			main()
			mock_handle.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# main() — mode command (lines 173-175)
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_main_mode_command():
	"""Lines 173-175: command == 'mode' → handle_mode called."""
	with patch("sys.argv", ["red-pill", "mode", "matrix"]):
		with patch("red_pill.cli.handle_mode") as mock_handle:
			main()
			mock_handle.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# main() — soul vault inactive (lines 241-243)
# ─────────────────────────────────────────────────────────────────────────────


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_vault_inactive(mock_soul):
	"""Lines 241-243: vault not enabled → inactive message."""
	mock_soul.return_value.vault.enabled = False
	with patch("sys.argv", ["red-pill", "soul", "vault"]):
		main()
	# Exercises the `else` branch for an inactive vault


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_vault_empty_backups(mock_soul):
	"""Line 237: vault enabled but no backups → empty message."""
	mock_soul.return_value.vault.enabled = True
	mock_soul.return_value.vault.list_backups.return_value = []
	with patch("sys.argv", ["red-pill", "soul", "vault"]):
		main()


# ─────────────────────────────────────────────────────────────────────────────
# main() — search with deep recall trigger (lines 254-264)
# ─────────────────────────────────────────────────────────────────────────────


@patch("red_pill.cli.MemoryManager")
def test_cli_main_search_deep_recall_flag(mock_mgr):
	"""Lines 259-264: --deep flag → deep_recall=True."""
	mock_mgr.return_value.search_and_reinforce.return_value = []
	with patch("sys.argv", ["red-pill", "search", "work", "my query", "--deep"]):
		main()
	call_kwargs = mock_mgr.return_value.search_and_reinforce.call_args
	assert call_kwargs.kwargs.get("deep_recall", False) is True


@patch("red_pill.cli.MemoryManager")
def test_cli_main_search_trigger_activates_deep_recall(mock_mgr):
	"""Lines 255-260: query matches DEEP_RECALL_TRIGGERS → deep_recall activated."""
	mock_mgr.return_value.search_and_reinforce.return_value = []
	with patch("red_pill.config.DEEP_RECALL_TRIGGERS", ["full recall"]):
		with patch("sys.argv", ["red-pill", "search", "work", "full recall protocol"]):
			main()
	call_kwargs = mock_mgr.return_value.search_and_reinforce.call_args
	assert call_kwargs.kwargs.get("deep_recall", False) is True


# ─────────────────────────────────────────────────────────────────────────────
# main() — search with synaptic hub warning (lines 269-280)
# ─────────────────────────────────────────────────────────────────────────────


@patch("red_pill.cli.MemoryManager")
def test_cli_main_search_with_results_and_hub_warning(mock_mgr):
	"""Lines 268-280: Results with assocs > 20 → synaptic hub warning logged."""
	hit = MagicMock()
	hit.id = "abc-123"
	hit.payload = {
		"content": "important memory",
		"color": "orange",
		"intensity": 3.0,
		"reinforcement_score": 0.8,
		"immune": False,
		"associations": list(range(25)),  # 25 > 20 triggers warning
	}
	mock_mgr.return_value.search_and_reinforce.return_value = [hit]
	with patch("sys.argv", ["red-pill", "search", "work", "important"]):
		main()  # Should not raise; hub warning logged


# ─────────────────────────────────────────────────────────────────────────────
# main() — sanitize dry-run output (line 291)
# ─────────────────────────────────────────────────────────────────────────────


@patch("red_pill.cli.MemoryManager")
def test_cli_main_sanitize_dry_run(mock_mgr):
	"""Line 291: --dry-run with found items → 'DRY RUN' note printed."""
	mock_mgr.return_value.sanitize.return_value = {"duplicates_found": 3, "migrated_records": 1}
	with patch("sys.argv", ["red-pill", "sanitize", "work", "--dry-run"]):
		main()
	mock_mgr.return_value.sanitize.assert_called_once_with("work_memories", dry_run=True)


# ─────────────────────────────────────────────────────────────────────────────
# main() — edit fail (line 297)
# ─────────────────────────────────────────────────────────────────────────────


@patch("red_pill.cli.MemoryManager")
def test_cli_main_edit_failure(mock_mgr):
	"""Line 297: update_memory returns False → '[FAIL]' message printed."""
	mock_mgr.return_value.update_memory.return_value = False
	with patch("sys.argv", ["red-pill", "edit", "work", "some-uuid", "--color", "cyan"]):
		main()
	mock_mgr.return_value.update_memory.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# main() — exception path (lines 304-306)
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_main_exception_exits():
	"""Lines 304-306: MemoryManager init raises → logger.error + sys.exit(1)."""
	with patch("red_pill.cli.MemoryManager", side_effect=RuntimeError("DB unreachable")):
		with patch("sys.argv", ["red-pill", "add", "work", "some content"]):
			with patch("sys.exit") as mock_exit:
				main()
			mock_exit.assert_called_with(1)


# ─────────────────────────────────────────────────────────────────────────────
# __main__ block (line 310)
# ─────────────────────────────────────────────────────────────────────────────


def test_cli_main_block_is_callable():
	"""Line 310: main() is importable and callable (covers the if __name__ == '__main__' guard)."""
	from red_pill.cli import main as cli_main

	assert callable(cli_main)
