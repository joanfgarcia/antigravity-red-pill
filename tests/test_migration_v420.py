import pytest
import uuid
from unittest.mock import MagicMock, patch
from red_pill.memory import MemoryManager
import red_pill.config as cfg

@pytest.fixture
def mock_qdrant():
	with patch('red_pill.memory.QdrantClient') as mock:
		yield mock

@pytest.fixture
def manager(mock_qdrant):
	mgr = MemoryManager()
	# Mock embeddings to avoid network
	mgr._get_vector = MagicMock(return_value=[0.1] * cfg.VECTOR_SIZE)
	return mgr

def test_full_schema_migration(manager, mock_qdrant):
	"""
	Simulates a collection with many engrams using the old pre-v4.2.0 schema.
	Verifies that 'sanitize' correctly brings them into compliance.
	"""
	# Old engrams: no color, no emotion, no intensity
	old_points = [
		MagicMock(id=str(uuid.uuid4()), payload={"content": f"Old memory {i}", "importance": 1.0, "reinforcement_score": 1.0})
		for i in range(5)
	]
	
	# Mixed engrams: some have partial data
	mixed_points = [
		MagicMock(id="partial_1", payload={"content": "Partial", "color": "yellow"}), # missing emotion/intensity
		MagicMock(id="duplicate_1", payload={"content": f"Old memory 0", "importance": 1.0}), # exact duplicate of the first old_point content
	]
	
	all_points = old_points + mixed_points
	
	# Mock scroll response
	manager.client.scroll.side_effect = [
		(all_points, None) # One single page for brevity
	]
	
	results = manager.sanitize("work_memories")
	
	# Assertions
	assert results["collection"] == "work_memories"
	assert results["duplicates_found"] == 1 # "Old memory 0" duplicated
	
	# All 5 old points + 1 partial point needed migration
	assert results["migrated_records"] == 6
	
	# Check that set_payload was called for the partial point to fill missing fields
	calls = manager.client.set_payload.call_args_list
	partial_call = next(c for c in calls if c[1]['points'] == ["partial_1"])
	assert "emotion" in partial_call[1]['payload']
	assert "intensity" in partial_call[1]['payload']
	# Should NOT overwrite existing color
	assert "color" not in partial_call[1]['payload'] 

def test_migration_idempotency(manager, mock_qdrant):
	"""Running sanitize on an already clean collection should do nothing."""
	clean_points = [
		MagicMock(id="clean_1", payload={
			"content": "Clean", 
			"color": "gray", 
			"emotion": "neutral", 
			"intensity": 1.0
		})
	]
	
	manager.client.scroll.return_value = (clean_points, None)
	
	results = manager.sanitize("work_memories")
	
	assert results["duplicates_found"] == 0
	assert results["migrated_records"] == 0
	assert not manager.client.set_payload.called
	assert not manager.client.delete.called
