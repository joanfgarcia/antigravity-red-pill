from unittest.mock import patch

import pytest

from red_pill.memory import MemoryManager
from red_pill.seed import seed_project


@pytest.fixture
def memory_manager():
	"""Provides a MemoryManager using an in-memory Qdrant instance."""
	with patch("red_pill.config.QDRANT_URL", None):
		with patch("red_pill.config.MILVUS_ENABLED", False):
			mgr = MemoryManager()
			seed_project(mgr)
			yield mgr


def test_full_memory_lifecycle(memory_manager):
	"""
	TEST-INT: Verifies the full pipeline:
	add_memory -> Qdrant -> decay -> search
	"""
	collection = "work_memories"

	# 1. Add Memory
	memory_id = memory_manager.add_memory(
		collection=collection, text="Integration test memory for the Red Pill Protocol.", color="orange", emotion="neutral", importance=5.0
	)
	assert memory_id is not None

	# Verify the memory actually made it in memory
	res = memory_manager.get_stats(collection)
	assert res["points_count"] >= 1

	# 2. Search Memory
	# The default fastembed stub in conftest returns a zero vector for everything.
	results = memory_manager.search_and_reinforce(collection=collection, query="test query", limit=50, deep_recall=False)
	assert len(results) > 0
	found_memory = next((m for m in results if "Integration test memory" in m.payload["content"]), None)
	assert found_memory is not None

	# 3. Decay (Erosion)
	initial_score = found_memory.payload["reinforcement_score"]

	import time

	with patch("time.time", return_value=time.time() + 3600 * 48):  # 48 hours later
		memory_manager.apply_erosion(collection, rate=0.5)

	# Retrieve again to check score without reinforcing
	raw_points = memory_manager.client.retrieve(collection_name=collection, ids=[found_memory.id], with_payload=True)

	score_after_erosion = raw_points[0].payload["reinforcement_score"]
	assert score_after_erosion < initial_score
