import os
import time
import asyncio
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
		asyncio.sleep(0.5)

		self.assertTrue(os.path.exists(self.test_state_file))
		mock_erosion.assert_called()
		erosion_count = mock_erosion.call_count

		# 2. Second addition within cooldown should NOT trigger again
		manager.add_memory("test_coll", "engram 2")
		asyncio.sleep(0.5)
		self.assertEqual(mock_erosion.call_count, erosion_count)

		# 3. Wait for cooldown and trigger again
		asyncio.sleep(2)
		manager.add_memory("test_coll", "engram 3")
		asyncio.sleep(0.5)
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
		asyncio.sleep(0.5)  # Background thread might log error but not crash main


if __name__ == "__main__":
	unittest.main()
