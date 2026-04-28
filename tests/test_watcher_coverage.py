import json
import subprocess
from unittest.mock import patch

from red_pill.swarm.watcher import inject_context_pill, notify_macos


def test_inject_context_pill_error():
	"""Test error handling when writing the context pill fails."""
	with patch("builtins.open", side_effect=PermissionError("Denied")):
		with patch("builtins.print") as mock_print:
			inject_context_pill("sender", "msg")
			mock_print.assert_any_call("[Watcher] Could not update pending messages: Denied")


def test_inject_context_pill_success(tmp_path):
	"""Test successful message injection."""
	test_file = tmp_path / "pending.json"
	with patch("red_pill.swarm.watcher.PENDING_MESSAGES_FILE", str(test_file)):
		inject_context_pill("sender1", "hello")
		assert test_file.exists()
		with open(test_file, "r") as f:
			data = json.load(f)
			assert data[0]["sender"] == "sender1"
			assert data[0]["preview"] == "hello"


def test_notify_macos_success():
	"""Test macOS notification successful call."""
	with patch("subprocess.run") as mock_run:
		notify_macos("Title", "Message")
		mock_run.assert_called_once()
		assert "display notification" in mock_run.call_args[0][0][2]


def test_notify_macos_error():
	"""Test macOS notification error handling."""
	with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "cmd")):
		with patch("builtins.print") as mock_print:
			notify_macos("Title", "Message")
			mock_print.assert_any_call("[Watcher] Notification failed: Command 'cmd' returned non-zero exit status 1.")


def test_watcher_main_lock_exists():
	"""MF-004: Test real de la salida segura cuando el watcher ya corre."""
	import pytest

	from red_pill.swarm.watcher import main

	with patch("os.path.exists", return_value=True):
		with patch("builtins.print") as mock_print:
			with patch("sys.exit", side_effect=SystemExit) as mock_exit:
				with pytest.raises(SystemExit):
					main()
				mock_print.assert_called_with("Watcher is already running.")
				mock_exit.assert_called_with(0)


def test_watcher_main_execution():
	"""MF-004: Test real de la ejecución exitosa de main()."""
	from red_pill.swarm.watcher import main

	with patch("os.path.exists", side_effect=[False, True]):  # 1 para check, 2 para finally
		with patch("builtins.open") as mock_open:
			with patch("os.getpid", return_value=1234):
				with patch("red_pill.swarm.watcher.simulate_firebase_listener") as mock_sim:
					with patch("os.remove") as mock_remove:
						main()

						# Verify lock was written
						mock_open.assert_called_once()
						mock_open.return_value.__enter__.return_value.write.assert_called_with("1234")

						# Verify listener called
						mock_sim.assert_called_once()

						# Verify cleanup
						mock_remove.assert_called_once()
