from unittest.mock import MagicMock, patch

import pytest

from red_pill.hive import HiveMind


@pytest.fixture
def mock_milvus():
	with patch("red_pill.hive.connections") as mock_conn, patch("red_pill.hive.Collection") as mock_coll, patch("red_pill.hive.utility") as mock_util:
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
	with patch("red_pill.config.MILVUS_ENABLED", True), patch("red_pill.config.HIVEMIND_DP_NOISE", False, create=True):
		hive = HiveMind()
		hive.connected = True
		mock_milvus["util"].has_collection.return_value = True
		vector = [0.1] * 384
		hive.transmit_experience("work_memories", "breakthrough", vector, {"importance": 1.0})
		assert mock_milvus["coll"].called
		call_args = mock_milvus["coll"].return_value.insert.call_args[0][0]
		assert call_args[0] == ["breakthrough"]
		assert call_args[1] == [vector]


def test_sync_from_hive(mock_milvus):
	with patch("red_pill.config.MILVUS_ENABLED", True):
		hive = HiveMind()
		hive.connected = True
		mock_milvus["util"].has_collection.return_value = True
		mock_hit = MagicMock()
		mock_hit.entity.get.side_effect = lambda x: {"content": "shared memory", "source_agent": "agent1", "importance": 0.9}.get(x)
		mock_hit.distance = 0.1
		mock_milvus["coll"].return_value.search.return_value = [[mock_hit]]
		results = hive.sync_from_hive([0.1] * 384, "work_memories")
		assert len(results) == 1
		assert results[0]["content"] == "shared memory"
		assert results[0]["source_agent"] == "agent1"


def test_smith_pre_filter(mock_milvus):
	"""TST-001: Verifies the forensic Smith Pre-Filter logic."""
	with patch("red_pill.config.MILVUS_ENABLED", True):
		hive = HiveMind()
		assert hive._passes_smith_filter("work_memories", "contact" + " me at joan" + "@exa" + "mple.com", {}) is False, "Email NOT blocked"
		assert hive._passes_smith_filter("work_memories", "API" + "_KEY = 'sk-" + "12345" + "67890abcdef'", {}) is False, "API Key NOT blocked"
		assert hive._passes_smith_filter("social_memories", "Neutral content", {}) is False, "Social collection NOT blocked"
		assert hive._passes_smith_filter("directive_memories", "Neutral content", {}) is False, "Directive collection NOT blocked"
		assert hive._passes_smith_filter("work_memories", "Sensitive finding", {"immune": True}) is False, "Immune engram NOT blocked"
		assert hive._passes_smith_filter("work_memories", "Optimal vector scaling achievement.", {"immune": False}) is True, (
			"Valid work memory blocked"
		)


def test_tls_enforcement_remote(mock_milvus):
	"""SEC-F03: Enforces TLS for non-local Milvus hosts."""
	with (
		patch("red_pill.config.MILVUS_ENABLED", True),
		patch("red_pill.config.MILVUS_HOST", "milvus.remote.com"),
		patch("red_pill.config.MILVUS_SECURE", False),
	):
		hive = HiveMind()
		assert hive.connected is False, "Remote insecure connection should be blocked"
		assert mock_milvus["conn"].connect.called is False


def test_tls_allowed_local(mock_milvus):
	"""SEC-F03: Allows insecure connections for localhost."""
	with (
		patch("red_pill.config.MILVUS_ENABLED", True),
		patch("red_pill.config.MILVUS_HOST", "localhost"),
		patch("red_pill.config.MILVUS_SECURE", False),
	):
		hive = HiveMind()
		assert hive.connected is True
		assert mock_milvus["conn"].connect.called is True
