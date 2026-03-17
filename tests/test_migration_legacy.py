import uuid
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.memory import MemoryManager


@pytest.fixture
def mock_qdrant():
	with patch("red_pill.memory.QdrantClient") as mock:
		yield mock


@pytest.fixture
def manager(mock_qdrant):
	mgr = MemoryManager()
	mgr._get_vector = MagicMock(return_value=[0.1] * cfg.VECTOR_SIZE)  # type: ignore
	return mgr


def test_full_schema_migration(manager, mock_qdrant):
	"""
	Simulates a collection with many engrams using the old pre-v4.2.0 schema.
	Verifies that 'sanitize' correctly brings them into compliance.
	"""
	base_payload = {"importance": 1.0, "created_at": 1000.0, "last_recalled_at": 1000.0, "schema_version": "v1.0"}
	old_points = [
		MagicMock(id=str(uuid.uuid4()), payload={**base_payload, "content": f"Old memory {i}", "reinforcement_score": 1.0}) for i in range(5)
	]
	mixed_points = [
		MagicMock(id="partial_1", payload={**base_payload, "content": "Partial", "color": "yellow"}),
		MagicMock(id="duplicate_1", payload={**base_payload, "content": "Old memory 0"}),
	]
	all_points = old_points + mixed_points
	manager.client.scroll.side_effect = [(all_points, None)]
	results = manager.sanitize("work_memories")
	assert results["collection"] == "work_memories"
	assert results["duplicates_found"] == 1
	assert results["migrated_records"] == 6
	calls = manager.client.batch_update_points.call_args_list
	operations = calls[0][1]["update_operations"]
	partial_call = next((op for op in operations if op.set_payload.points == ["partial_1"]))
	assert "emotion" in partial_call.set_payload.payload
	assert "intensity" in partial_call.set_payload.payload
	assert partial_call.set_payload.payload.get("color") == "yellow"


def test_migration_idempotency(manager, mock_qdrant):
	"""Running sanitize on an already clean collection should do nothing."""
	clean_points = [
		MagicMock(
			id="clean_1",
			payload={"content": "Clean", "color": "gray", "emotion": "neutral", "intensity": 1.0, "schema_version": cfg.CURRENT_SCHEMA_VERSION},
		)
	]
	manager.client.scroll.return_value = (clean_points, None)
	results = manager.sanitize("work_memories")
	assert results["duplicates_found"] == 0
	assert results["migrated_records"] == 0
	assert not manager.client.batch_update_points.called
	assert not manager.client.delete.called
