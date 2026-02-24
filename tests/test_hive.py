import pytest
from unittest.mock import MagicMock, patch
from red_pill.hive import HiveMind

@pytest.fixture
def mock_milvus():
	with patch("red_pill.hive.connections") as mock_conn, \
		 patch("red_pill.hive.Collection") as mock_coll, \
		 patch("red_pill.hive.utility") as mock_util:
		yield {"conn": mock_conn, "coll": mock_coll, "util": mock_util}

def test_hive_initialization(mock_milvus):
	with patch("red_pill.config.MILVUS_ENABLED", True):
		hive = HiveMind()
		assert hive.enabled is True
		assert mock_milvus["conn"].connect.called

def test_hive_disabled():
	with patch("red_pill.config.MILVUS_ENABLED", False):
		hive = HiveMind()
		assert hive.enabled is False
		assert hive.connected is False

def test_transmit_experience(mock_milvus):
	with patch("red_pill.config.MILVUS_ENABLED", True):
		hive = HiveMind()
		hive.connected = True
		mock_milvus["util"].has_collection.return_value = True
		
		vector = [0.1] * 384
		hive.transmit_experience("test_hive", "breakthrough", vector, {"importance": 1.0})
		
		assert mock_milvus["coll"].called
		# Check if insert was called with columnar data
		call_args = mock_milvus["coll"].return_value.insert.call_args[0][0]
		assert call_args[0] == ["breakthrough"]
		assert call_args[1] == [vector]

def test_sync_from_hive(mock_milvus):
	with patch("red_pill.config.MILVUS_ENABLED", True):
		hive = HiveMind()
		hive.connected = True
		mock_milvus["util"].has_collection.return_value = True
		
		# Mock search result
		mock_hit = MagicMock()
		mock_hit.entity.get.side_effect = lambda x: {"content": "shared memory", "source_agent": "agent1", "importance": 0.9}.get(x)
		mock_hit.distance = 0.1
		mock_milvus["coll"].return_value.search.return_value = [[mock_hit]]
		
		results = hive.sync_from_hive([0.1]*384, "test_hive")
		assert len(results) == 1
		assert results[0]["content"] == "shared memory"
		assert results[0]["source_agent"] == "agent1"
