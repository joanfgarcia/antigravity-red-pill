import argparse
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from red_pill.cli import (
	handle_audit,
	handle_benchmark,
	handle_heal,
	handle_identity,
	main,
	switch_skin
)


def test_switch_skin_invalid():
	result = switch_skin("non_existent_skin")
	assert "Invalid mode" in result


def test_handle_audit_success():
	with patch("subprocess.run") as mock_run:
		handle_audit()
		mock_run.assert_called_once()
		assert "pre_pr_audit.sh" in mock_run.call_args[0][0][1]


def test_handle_audit_failure():
	with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd")):
		with pytest.raises(SystemExit) as exc:
			handle_audit()
		assert exc.value.code == 1


def test_handle_heal():
	with patch("subprocess.run") as mock_run:
		handle_heal(dry_run=True)
		assert "--dry-run" in mock_run.call_args[0][0]
		handle_heal(dry_run=False)
		assert "--dry-run" not in mock_run.call_args[0][0]


def test_handle_benchmark():
	with patch("subprocess.run") as mock_run:
		handle_benchmark()
		assert "sovereignty_benchmark.py" in mock_run.call_args[0][0][1]


def test_handle_identity_bootstrap():
	args = argparse.Namespace(
		id_cmd="bootstrap",
		ai_name="Aleth",
		ai_role="Architect",
		user_name="Joan",
		user_role="Operator",
		skin="matrix"
	)
	with patch("subprocess.run") as mock_run:
		handle_identity(args)
		cmd = mock_run.call_args[0][0]
		assert "--ai-name" in cmd
		assert "Aleth" in cmd
		assert "--skin" in cmd
		assert "matrix" in cmd


def test_handle_identity_refresh():
	args = argparse.Namespace(id_cmd="refresh")
	with patch("subprocess.run") as mock_run:
		handle_identity(args)
		assert "wake_up_v6.py" in mock_run.call_args[0][0][1]


def test_main_sleep_error():
	# Test the error handling in sleep command
	test_args = ["red-pill", "sleep", "--mode", "deep"]
	with patch("sys.argv", test_args):
		with patch("red_pill.metabolism.sleep.perform_sleep_cycle", side_effect=Exception("Consolidation error")):
			with patch("red_pill.memory.MemoryManager"):
				# main() doesn't return, so we check if it prints error
				with patch("builtins.print") as mock_print:
					main()
					mock_print.assert_any_call("[ERROR] Sleep cycle interrupted: Consolidation error")


def test_main_backup_error():
	test_args = ["red-pill", "backup", "--collections", "work_memories"]
	with patch("sys.argv", test_args):
		mock_mgr = MagicMock()
		mock_mgr.create_bunker_snapshot.return_value = {"work_memories": "ERROR: partial failure"}
		with patch("red_pill.cli.MemoryManager", return_value=mock_mgr):
			with patch("builtins.print") as mock_print:
				main()
				mock_print.assert_any_call("[FAIL] work_memories: ERROR: partial failure")


def test_main_signal_logic():
	test_args = ["red-pill", "signal", "Test message", "--title", "Test Title", "--sound"]
	with patch("sys.argv", test_args):
		with patch("red_pill.utils.observer.notify_user") as mock_notify:
			with patch("red_pill.cli.MemoryManager") as mock_mgr:
				main()
				mock_notify.assert_any_call("Test Title", "Test message", sound=True)
				# mock_mgr.return_value.add_memory.assert_called_once()


def test_main_swarm_audit_details():
	test_args = ["red-pill", "swarm", "audit", "--path", "/tmp"]
	with patch("sys.argv", test_args):
		mock_gru = MagicMock()
		mock_res = MagicMock()
		mock_res.status = "success"
		mock_res.minion_id = "agent-smith-123"
		mock_res.result = {
			"security_score": 95,
			"files_scanned": 10,
			"findings": [{"severity": "CRITICAL", "file": "key.py", "line": 1, "msg": "leak"}]
		}
		
		# Define an async mock for deploy_swarm
		async def mock_deploy(*args, **kwargs):
			return [mock_res]
		
		mock_gru.deploy_swarm = mock_deploy
		
		with patch("red_pill.cli.GruOrchestrator", return_value=mock_gru):
			with patch("red_pill.cli.SmithMinion"):
				with patch("builtins.print") as mock_print:
					main()
					mock_print.assert_any_call("- Score de Seguridad: 95/100")


def test_main_init_command():
	test_args = ["red-pill", "init", "--flow", "simple"]
	with patch("sys.argv", test_args):
		with patch("subprocess.run") as mock_run:
			with patch("red_pill.utils.observer.notify_user") as mock_notify:
				main()
				mock_run.assert_called_once()
				assert "specsmd@latest" in mock_run.call_args[0][0]
				mock_notify.assert_called_once()
