import os
import sys
import runpy
from unittest.mock import MagicMock, patch

import pytest


def test_watcher_main_block_coverage(tmp_path):
	"""Cover the __main__ block of watcher.py."""
	lock_file = tmp_path / "watcher.lock"
	with patch("red_pill.swarm.watcher.WATCHER_LOCK_PATH", str(lock_file)):
		# Case 1: Already running
		lock_file.write_text("123")
		with patch("sys.exit") as mock_exit:
			with patch("builtins.print") as mock_print:
				# run_module might raise SystemExit instead of just calling the mock
				try:
					runpy.run_module("red_pill.swarm.watcher", run_name="__main__")
				except SystemExit:
					pass
				mock_exit.assert_called_with(0)
				mock_print.assert_any_call("Watcher is already running.")
		
		# Case 2: Success path
		if lock_file.exists():
			lock_file.unlink()
		with patch("red_pill.swarm.watcher.simulate_firebase_listener"):
			with patch("os.getpid", return_value=456):
				runpy.run_module("red_pill.swarm.watcher", run_name="__main__")
				assert not lock_file.exists()


def test_daemon_main_block_coverage():
	"""Cover the __main__ block of memory_daemon.py."""
	with patch("red_pill.memory_daemon.MemoryDaemon") as mock_daemon_class:
		mock_instance = mock_daemon_class.return_value
		# Mock start to do nothing
		mock_instance.start = MagicMock()
		with patch("signal.signal"):
			runpy.run_module("red_pill.memory_daemon", run_name="__main__")
			assert mock_instance.start.called
