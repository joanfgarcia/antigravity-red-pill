import os
import time
import unittest
from unittest.mock import MagicMock, patch

import red_pill.config as cfg
from red_pill.memory import MemoryManager


class TestMetabolism(unittest.TestCase):
	def setUp(self):
		# Use a temporary state file for testing
		self.test_state_file = "/tmp/.red_pill_test_metabolism"
		cfg.METABOLISM_STATE_FILE = self.test_state_file
		cfg.METABOLISM_ENABLED = True
		cfg.METABOLISM_COOLDOWN = 2  # 2 seconds for test
		if os.path.exists(self.test_state_file):
			os.remove(self.test_state_file)

	def tearDown(self):
		if os.path.exists(self.test_state_file):
			os.remove(self.test_state_file)

	@patch("red_pill.memory.QdrantClient")
	@patch("red_pill.memory.MemoryManager._get_vector")
	@patch("red_pill.memory.MemoryManager.apply_erosion")
	def test_reactive_trigger(self, mock_erosion, mock_vector, mock_qdrant):
		mock_vector.return_value = [0.1] * cfg.VECTOR_SIZE
		manager = MemoryManager(url="http://mock:6333")

		# 1. First addition should trigger metabolism
		manager.add_memory("test_coll", "engram 1")

		# Give it a tiny bit of time to start the thread
		time.sleep(0.5)

		self.assertTrue(os.path.exists(self.test_state_file))
		mock_erosion.assert_called()
		erosion_count = mock_erosion.call_count

		# 2. Second addition within cooldown should NOT trigger again
		manager.add_memory("test_coll", "engram 2")
		time.sleep(0.5)
		self.assertEqual(mock_erosion.call_count, erosion_count)

		# 3. Wait for cooldown and trigger again
		time.sleep(2)
		manager.add_memory("test_coll", "engram 3")
		time.sleep(0.5)
		self.assertGreater(mock_erosion.call_count, erosion_count)

	@patch("red_pill.memory.QdrantClient")
	@patch("red_pill.memory.MemoryManager._get_vector")
	def test_metabolism_error_safe(self, mock_vector, mock_qdrant):
		# Verify that metabolism failures don't crash add_memory
		mock_vector.return_value = [0.1] * cfg.VECTOR_SIZE
		manager = MemoryManager(url="http://mock:6333")
		manager.apply_erosion = MagicMock(side_effect=Exception("Database down"))

		# This should not raise
		id = manager.add_memory("test_coll", "safe engram")
		self.assertIsNotNone(id)
		time.sleep(0.5)  # Background thread might log error but not crash main

	# ── CQ-001: skip_next_erosion flag tests ───────────────────────────────

	@patch("red_pill.memory.QdrantClient")
	def test_read_write_state_roundtrip(self, mock_qdrant):
		"""CQ-001: JSON state roundtrip — last_run and skip_next_erosion preserved."""
		manager = MemoryManager(url="http://mock:6333")
		with open(self.test_state_file, "w+") as f:
			manager._write_metabolism_state(f, 1234567890.0, skip_next_erosion=True)
		with open(self.test_state_file, "r+") as f:
			last_run, skip = manager._read_metabolism_state(f)
		self.assertAlmostEqual(last_run, 1234567890.0, places=3)
		self.assertTrue(skip)

	@patch("red_pill.memory.QdrantClient")
	def test_read_legacy_float_state(self, mock_qdrant):
		"""CQ-001: Backward-compat — bare float state files are still parsed."""
		manager = MemoryManager(url="http://mock:6333")
		with open(self.test_state_file, "w") as f:
			f.write("1234567890.5")
		with open(self.test_state_file, "r+") as f:
			last_run, skip = manager._read_metabolism_state(f)
		self.assertAlmostEqual(last_run, 1234567890.5, places=3)
		self.assertFalse(skip)  # Legacy files have no flag — defaults to False

	@patch("red_pill.memory.QdrantClient")
	def test_read_empty_state(self, mock_qdrant):
		"""CQ-001: Empty state file returns (0.0, False) safely."""
		manager = MemoryManager(url="http://mock:6333")
		open(self.test_state_file, "w").close()  # Create empty file
		with open(self.test_state_file, "r+") as f:
			last_run, skip = manager._read_metabolism_state(f)
		self.assertEqual(last_run, 0.0)
		self.assertFalse(skip)

	@patch("red_pill.memory.QdrantClient")
	@patch("red_pill.memory.MemoryManager.apply_erosion")
	def test_skip_next_erosion_flag_prevents_erosion(self, mock_erosion, mock_qdrant):
		"""
		CQ-001: When skip_next_erosion=True is in state, the cycle logs and returns
		without calling apply_erosion.
		"""
		manager = MemoryManager(url="http://mock:6333")
		# Write state with cooldown already expired AND skip_next_erosion=True
		past_time = time.time() - cfg.METABOLISM_COOLDOWN - 10
		import json

		with open(self.test_state_file, "w") as f:
			json.dump({"last_run": past_time, "skip_next_erosion": True}, f)

		manager._run_metabolism_cycle()

		# Erosion must NOT have been called
		mock_erosion.assert_not_called()

		# Flag must be cleared in state file
		with open(self.test_state_file, "r+") as f:
			_, skip_after = manager._read_metabolism_state(f)
		self.assertFalse(skip_after, "Flag should be cleared after being consumed")

	@patch("red_pill.memory.QdrantClient")
	@patch("red_pill.memory.MemoryManager.apply_erosion")
	def test_normal_cycle_after_flag_cleared_runs_erosion(self, mock_erosion, mock_qdrant):
		"""
		CQ-001: After the flag is consumed (cleared), the NEXT cycle runs erosion normally.
		"""
		manager = MemoryManager(url="http://mock:6333")
		# First, write state with skip_next_erosion=True (flag active)
		past_time = time.time() - cfg.METABOLISM_COOLDOWN - 10
		import json

		with open(self.test_state_file, "w") as f:
			json.dump({"last_run": past_time, "skip_next_erosion": True}, f)

		# First cycle: flag consumed, erosion skipped
		manager._run_metabolism_cycle()
		mock_erosion.assert_not_called()

		# Manually rewind the state file's last_run so cooldown expires
		past_time2 = time.time() - cfg.METABOLISM_COOLDOWN - 10
		with open(self.test_state_file, "w") as f:
			json.dump({"last_run": past_time2, "skip_next_erosion": False}, f)

		# Second cycle: flag is False, erosion RUNS
		manager._run_metabolism_cycle()
		mock_erosion.assert_called()


if __name__ == "__main__":
	unittest.main()
