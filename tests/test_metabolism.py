import os
import time
import unittest
from unittest.mock import MagicMock, patch

import red_pill.config as cfg
from red_pill.memory import MemoryManager


class TestMetabolism(unittest.TestCase):
	def setUp(self):
		self.test_state_file = "/tmp/.red_pill_test_metabolism"
		cfg.METABOLISM_STATE_FILE = self.test_state_file
		cfg.METABOLISM_ENABLED = True
		cfg.METABOLISM_STRATEGY = "CLASSIC"
		cfg.METABOLISM_COOLDOWN = 2
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
		manager.add_memory("test_coll", "engram 1")
		if manager._metabolism_thread:
			manager._metabolism_thread.join()
		self.assertTrue(os.path.exists(self.test_state_file))
		mock_erosion.assert_called()
		erosion_count = mock_erosion.call_count

		manager.add_memory("test_coll", "engram 2")
		if manager._metabolism_thread:
			manager._metabolism_thread.join()
		self.assertEqual(mock_erosion.call_count, erosion_count)

		with patch("time.time", return_value=time.time() + 5):
			manager.add_memory("test_coll", "engram 3")
			if manager._metabolism_thread:
				manager._metabolism_thread.join()
		self.assertGreater(mock_erosion.call_count, erosion_count)

	@patch("red_pill.memory.QdrantClient")
	@patch("red_pill.memory.MemoryManager._get_vector")
	def test_metabolism_error_safe(self, mock_vector, mock_qdrant):
		mock_vector.return_value = [0.1] * cfg.VECTOR_SIZE
		manager = MemoryManager(url="http://mock:6333")
		manager.apply_erosion = MagicMock(side_effect=Exception("Database down"))  # type: ignore
		id = manager.add_memory("test_coll", "safe engram")
		self.assertIsNotNone(id)
		if manager._metabolism_thread:
			manager._metabolism_thread.join()

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
		self.assertFalse(skip)

	@patch("red_pill.memory.QdrantClient")
	def test_read_empty_state(self, mock_qdrant):
		"""CQ-001: Empty state file returns (0.0, False) safely."""
		manager = MemoryManager(url="http://mock:6333")
		open(self.test_state_file, "w").close()
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
		past_time = time.time() - cfg.METABOLISM_COOLDOWN - 10
		import json

		with open(self.test_state_file, "w") as f:
			json.dump({"last_run": past_time, "skip_next_erosion": True}, f)
		manager._run_metabolism_cycle()
		mock_erosion.assert_not_called()
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
		past_time = time.time() - cfg.METABOLISM_COOLDOWN - 10
		import json

		with open(self.test_state_file, "w") as f:
			json.dump({"last_run": past_time, "skip_next_erosion": True}, f)
		manager._run_metabolism_cycle()
		mock_erosion.assert_not_called()
		past_time2 = time.time() - cfg.METABOLISM_COOLDOWN - 10
		with open(self.test_state_file, "w") as f:
			json.dump({"last_run": past_time2, "skip_next_erosion": False}, f)
		manager._run_metabolism_cycle()
		mock_erosion.assert_called()


if __name__ == "__main__":
	unittest.main()
