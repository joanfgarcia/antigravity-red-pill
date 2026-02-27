from unittest.mock import patch

import pytest

from red_pill.hive import HiveMind


@pytest.fixture
def mock_milvus():
	with patch("red_pill.hive.connections") as mock_conn, patch("red_pill.hive.Collection") as mock_coll, patch("red_pill.hive.utility") as mock_util:
		yield {"conn": mock_conn, "coll": mock_coll, "util": mock_util}


def test_hive_connection_error(mock_milvus):
	"""Test handling of connection failures."""
	mock_milvus["conn"].connect.side_effect = Exception("No Milvus here")
	hive = HiveMind()
	assert hive.connected is False


def test_transmit_experience_failure(mock_milvus):
	"""Test transmission failures."""
	mock_milvus["util"].has_collection.side_effect = Exception("DB dead")
	hive = HiveMind()
	hive.connected = True
	# Should not crash
	hive.transmit_experience("work_memories", "breakthrough", [0.1] * 384, {})


def test_sync_from_hive_empty(mock_milvus):
	"""Test sync when collection doesn't exist."""
	mock_milvus["util"].has_collection.return_value = False
	hive = HiveMind()
	hive.connected = True
	assert hive.sync_from_hive([0.1] * 384, "hive_work") == []


def test_sync_from_hive_error(mock_milvus):
	"""Test sync failure handling."""
	mock_milvus["util"].has_collection.return_value = True
	mock_milvus["coll"].return_value.search.side_effect = Exception("Search error")
	hive = HiveMind()
	hive.connected = True
	assert hive.sync_from_hive([0.1] * 384, "hive_work") == []
