from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.memory import MemoryManager


@pytest.fixture
def mock_qdrant():
	with patch('red_pill.memory.QdrantClient') as mock:
		yield mock

@pytest.fixture
def manager(mock_qdrant):
	mgr = MemoryManager()
	mgr._get_vector = MagicMock(return_value=[0.1] * cfg.VECTOR_SIZE)
	return mgr

def test_emotional_erosion(manager, mock_qdrant):
	# Setup multipliers
	cfg.EROSION_RATE = 0.1
	cfg.EMOTIONAL_DECAY_MULTIPLIERS["orange"] = 1.5
	cfg.EMOTIONAL_DECAY_MULTIPLIERS["yellow"] = 0.5

	# Mock points with different colors
	# Orange: 1.0 - (0.1 * 1.5) = 0.85
	point_orange = MagicMock()
	point_orange.id = "orange_1"
	point_orange.payload = {"reinforcement_score": 1.0, "color": "orange", "immune": False}

	# Yellow: 1.0 - (0.1 * 0.5) = 0.95
	point_yellow = MagicMock()
	point_yellow.id = "yellow_1"
	point_yellow.payload = {"reinforcement_score": 1.0, "color": "yellow", "immune": False}

	manager.client.scroll.side_effect = [
		([point_orange, point_yellow], None)
	]

	manager.apply_erosion("test_col")

	# Verify batch_update_points calls
	calls = manager.client.batch_update_points.call_args_list
	assert len(calls) == 1
	operations = calls[0][1]['update_operations']

	results = {}
	for op in operations:
		results[op.set_payload.points[0]] = op.set_payload.payload['reinforcement_score']

	assert results["orange_1"] == 0.85
	assert results["yellow_1"] == 0.95

def test_add_memory_with_emotion(manager, mock_qdrant):
	manager.add_memory(
		"test_col",
		"Feeling anxious about the demo",
		color="orange",
		emotion="anxiety",
		intensity=9.0
	)

	assert manager.client.upsert.called
	args, kwargs = manager.client.upsert.call_args
	payload = kwargs['points'][0].payload

	assert payload["color"] == "orange"
	assert payload["emotion"] == "anxiety"
	assert payload["intensity"] == 9.0
	assert payload["reinforcement_score"] == 1.0

def test_invalid_color_rejection(manager):
	from pydantic import ValidationError
	with pytest.raises(ValidationError):
		manager.add_memory("test_col", "content", color="pink") # Pink is not on our spectrum!

def test_sanitation(manager, mock_qdrant):
	# Mocking points: one duplicate, one old schema (missing color)
	p1 = MagicMock(id="1", payload={"content": "duplicate", "color": "gray"})
	p2 = MagicMock(id="2", payload={"content": "duplicate", "color": "gray"})
	p3 = MagicMock(id="3", payload={"content": "unique", "intensity": 5.0}) # Missing color/emotion

	manager.client.scroll.side_effect = [
		([p1, p2, p3], None)
	]

	results = manager.sanitize("test_col")

	# Verify duplicates were deleted
	# manager.client.delete should be called with point 2
	assert manager.client.delete.called
	args, kwargs = manager.client.delete.call_args
	assert "2" in kwargs['points_selector'].points

	# Verify migration (point 3 missing color/emotion)
	# manager.client.batch_update_points should be called for p3
	assert manager.client.batch_update_points.called
	# Check if point 3 was updated with defaults
	calls = manager.client.batch_update_points.call_args_list
	operations = calls[0][1]['update_operations']
	p3_update = next(op for op in operations if op.set_payload.points == ["3"])
	assert p3_update.set_payload.payload['color'] == "gray"
	assert p3_update.set_payload.payload['emotion'] == "neutral"

	assert results["duplicates_found"] == 1
	assert results["migrated_records"] == 2
