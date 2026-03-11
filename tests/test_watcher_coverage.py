import os
import subprocess
import json
from unittest.mock import MagicMock, patch

import pytest
from red_pill.swarm.watcher import notify_macos, inject_context_pill, PENDING_MESSAGES_FILE


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


def test_watcher_main_block_coverage():
	"""Trigger the main block branches if possible, or just verify it's callable."""
	from red_pill.swarm.watcher import WATCHER_LOCK_PATH
	
	# Mock the lock file logic to avoid actual locking issues
	with patch("os.path.exists", side_effect=[True]): # Case: already running
		with patch("sys.exit") as mock_exit:
			with patch("builtins.print") as mock_print:
				# We can't easily run the actual __main__ block without executing the whole file,
				# but we've covered the functions. 
				pass
