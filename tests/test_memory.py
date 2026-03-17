import uuid
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as config
from red_pill.memory import MemoryManager


@pytest.fixture
def mock_qdrant():
	with patch("red_pill.memory.QdrantClient") as mock:
		yield mock


@pytest.fixture
def manager(mock_qdrant):
	mgr = MemoryManager()
	mgr._get_vector = MagicMock(return_value=[0.1] * config.VECTOR_SIZE)
	return mgr


def test_linear_decay(manager):
	config.DECAY_STRATEGY = "linear"
	# 1.0 - 0.05 = 0.95
	assert manager._calculate_decay(1.0, 0.05) == 0.95
	# 0.04 - 0.05 = 0.0
	assert manager._calculate_decay(0.04, 0.05) == 0.0


def test_exponential_decay(manager):
	config.DECAY_STRATEGY = "exponential"
	# 1.0 * (1 - 0.05) = 0.95
	assert manager._calculate_decay(1.0, 0.05) == 0.95
	# 2.0 * (1 - 0.1) = 1.8
	assert manager._calculate_decay(2.0, 0.1) == 1.8


def test_exponential_decay_floor(manager):
	config.DECAY_STRATEGY = "exponential"
	# Test bug where 0.01 rounded to 2 decimal places stays 0.01
	# current=0.01, rate=0.05 -> 0.01 * 0.95 = 0.0095 -> round(0.01)
	# Our fix should force it down to 0.00
	assert manager._calculate_decay(0.01, 0.05) == 0.0


def test_dormancy_filter(manager, mock_qdrant):
	mock_response = MagicMock()
	mock_response.points = []
	manager.client.query_points.return_value = mock_response

	# Normal search: should have filter
	manager.search_and_reinforce("test_col", "query", deep_recall=False)
	args, kwargs = manager.client.query_points.call_args
	assert kwargs["query_filter"] is not None
	# Check that filter has gte=0.2
	range_cond = kwargs["query_filter"].must[0].range
	assert range_cond.gte == 0.2

	# Deep Recall: filter should be None
	manager.search_and_reinforce("test_col", "query", deep_recall=True)
	args, kwargs = manager.client.query_points.call_args
	assert kwargs["query_filter"] is None


def test_manual_id_injection(manager, mock_qdrant):
	# Test that add_memory respects a manual point_id
	manual_id = str(uuid.uuid4())
	returned_id = manager.add_memory("test_col", "content", point_id=manual_id)

	assert returned_id == manual_id
	args, kwargs = manager.client.upsert.call_args
	assert kwargs["points"][0].id == manual_id


def test_strict_id_validation(manager, mock_qdrant):
	# Test that _reinforce_points filters out garbage strings
	real_uuid = str(uuid.uuid4())
	increments = {real_uuid: 0.1, "not-a-uuid": 0.05}

	manager._reinforce_points("test_col", [real_uuid, "not-a-uuid"], increments)
	args, kwargs = manager.client.retrieve.call_args
	assert real_uuid in kwargs["ids"]
	assert "not-a-uuid" not in kwargs["ids"]


def test_system_keys_handled_instead_of_failing(manager, mock_qdrant):
	# Test that reserved keys like 'immune', 'importance', etc. are popped
	# and handled without causing a ValidationError
	manager.add_memory("test_col", "content", metadata={"immune": True, "importance": 5.0})
	# Verification happens in the mock collection calls, but here we just ensure NO CRASH
