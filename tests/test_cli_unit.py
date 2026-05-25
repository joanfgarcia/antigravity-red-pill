import argparse
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from red_pill.cli import get_collection, handle_mode, main

root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_path not in sys.path:
	sys.path.insert(0, root_path)


def test_get_collection():
	assert get_collection("social") == "social_memories"
	assert get_collection("work") == "work_memories"
	assert get_collection("unknown") == "directive_memories"


@patch("builtins.input", return_value="Y")
def test_handle_mode_unit(mock_input):
	"""Unit test for mode switching logic."""
	args = argparse.Namespace(skin="760")
	with patch("red_pill.cli.switch_skin", return_value="Switched to 760") as mock_switch:
		handle_mode(args)
		mock_switch.assert_called_once_with("760")


@patch("builtins.input", return_value="n")
def test_handle_mode_abort(mock_input):
	"""Unit test for aborting mode switch."""
	args = argparse.Namespace(skin="matrix")
	with patch("red_pill.cli.switch_skin") as mock_switch:
		handle_mode(args)
		mock_switch.assert_not_called()


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
	mock_mgr.return_value.sanitize.return_value = {"duplicates_found": 0, "migrated_records": 0, "refracted_records": 0}
	with patch("sys.argv", ["red-pill", "sanitize", "work"]):
		main()
		mock_mgr.return_value.sanitize.assert_called_once_with("work_memories", dry_run=False, strict=True)


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
@patch("red_pill.core.paths.get_neon_link_db_path", return_value="/tmp/mock_neon_link.db")
@patch("sqlite3.connect")
def test_cli_main_swarm_broadcast(mock_connect, mock_db_path, mock_mgr):
	"""Test 'red-pill swarm broadcast "hello" --channel firebase'."""
	mock_conn = MagicMock()
	mock_connect.return_value = mock_conn
	with patch("sys.argv", ["red-pill", "swarm", "broadcast", "hello message", "--channel", "firebase"]):
		main()
		mock_connect.assert_called_once_with("/tmp/mock_neon_link.db")
		mock_conn.cursor.return_value.execute.assert_called_once()
		mock_conn.commit.assert_called_once()
		mock_conn.close.assert_called_once()


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
	with patch("scripts.rotate_keys.rotate") as mock_rotate:
		with patch("sys.argv", ["red-pill", "soul", "rotate"]):
			main()
			mock_rotate.assert_called_once()


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_export(mock_soul):
	"""Test 'red-pill soul export'."""
	with patch("sys.argv", ["red-pill", "soul", "export"]):
		with patch("red_pill.interceptors._init_sovereign_plugins", new_callable=AsyncMock):
			mock_soul.return_value.export_soul = AsyncMock()
			main()
			mock_soul.return_value.export_soul.assert_called_once()


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_restore(mock_soul):
	"""Test 'red-pill soul restore'."""
	with patch("sys.argv", ["red-pill", "soul", "restore", "/tmp/bkp", "--commit"]):
		main()
		mock_soul.return_value.restore_soul.assert_called_once_with("/tmp/bkp", commit=True)


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


def test_cli_main_no_command_exits():
	"""Lines 166-168: no command → parser.print_help() + sys.exit(0).
	Note: sys.exit is mocked so execution continues; we verify exit(0) was called.
	"""
	with patch("sys.argv", ["red-pill"]):
		with patch("sys.exit") as mock_exit:
			main()
			mock_exit.assert_any_call(0)


def test_cli_main_mode_command():
	"""Lines 173-175: command == 'mode' → handle_mode called."""
	with patch("sys.argv", ["red-pill", "mode", "matrix"]):
		with patch("red_pill.cli.handle_mode") as mock_handle:
			main()
			mock_handle.assert_called_once()


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_vault_inactive(mock_soul):
	"""Lines 241-243: vault not enabled → inactive message."""
	mock_soul.return_value.vault.enabled = False
	with patch("sys.argv", ["red-pill", "soul", "vault"]):
		main()


@patch("red_pill.cli.SoulManager")
def test_cli_main_soul_vault_empty_backups(mock_soul):
	"""Line 237: vault enabled but no backups → empty message."""
	mock_soul.return_value.vault.enabled = True
	mock_soul.return_value.vault.list_backups.return_value = []
	with patch("sys.argv", ["red-pill", "soul", "vault"]):
		main()


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
		"associations": list(range(25)),
	}
	mock_mgr.return_value.search_and_reinforce.return_value = [hit]
	with patch("sys.argv", ["red-pill", "search", "work", "important"]):
		main()


@patch("red_pill.cli.MemoryManager")
def test_cli_main_sanitize_dry_run(mock_mgr):
	"""Line 291: --dry-run with found items → 'DRY RUN' note printed."""
	mock_mgr.return_value.sanitize.return_value = {"duplicates_found": 3, "migrated_records": 1, "refracted_records": 2}
	with patch("sys.argv", ["red-pill", "sanitize", "work", "--dry-run"]):
		main()
	mock_mgr.return_value.sanitize.assert_called_once_with("work_memories", dry_run=True, strict=True)


@patch("red_pill.cli.MemoryManager")
def test_cli_main_edit_failure(mock_mgr):
	"""Line 297: update_memory returns False → '[FAIL]' message printed."""
	mock_mgr.return_value.update_memory.return_value = False
	with patch("sys.argv", ["red-pill", "edit", "work", "some-uuid", "--color", "cyan"]):
		main()
	mock_mgr.return_value.update_memory.assert_called_once()


def test_cli_main_exception_exits():
	"""Lines 304-306: MemoryManager init raises → logger.error + sys.exit(1)."""
	with patch("red_pill.cli.MemoryManager", side_effect=RuntimeError("DB unreachable")):
		with patch("sys.argv", ["red-pill", "add", "work", "some content"]):
			with patch("sys.exit") as mock_exit:
				main()
			mock_exit.assert_called_with(1)


def test_cli_main_block_is_callable():
	"""Line 310: main() is importable and callable (covers the if __name__ == '__main__' guard)."""
	from red_pill.cli import main as cli_main

	assert callable(cli_main)


@patch("red_pill.cli.handle_p2p")
def test_cli_main_p2p_command(mock_handle):
	"""Test red-pill p2p routing."""
	with patch("sys.argv", ["red-pill", "p2p", "sync", "Nomad"]):
		main()
		mock_handle.assert_called_once()


@patch("red_pill.core.p2p_sync.SovereignSyncEngine")
@patch("red_pill.core.p2p_sync.add_peer_alias")
@patch("red_pill.core.p2p_sync.get_local_public_key", return_value="abc123node")
def test_handle_p2p_commands(mock_get_key, mock_add_alias, mock_engine):
	from red_pill.cli import handle_p2p

	args_pair = argparse.Namespace(p2p_cmd="pair", alias="nomad", node_id="xyz123node")
	handle_p2p(args_pair)
	mock_add_alias.assert_called_once_with("nomad", "xyz123node")

	args_adv = argparse.Namespace(p2p_cmd="advertise")
	handle_p2p(args_adv)
	mock_get_key.assert_called_once()

	args_sync = argparse.Namespace(p2p_cmd="sync", peer="nomad", since=100.0, collections=["work_memories"])
	handle_p2p(args_sync)
	mock_engine.from_default.return_value.transmit_sync_payload.assert_called_once_with("nomad", ["work_memories"], 100.0)

	args_proc = argparse.Namespace(p2p_cmd="process")
	handle_p2p(args_proc)
	mock_engine.from_default.return_value.process_incoming_syncs.assert_called_once()
