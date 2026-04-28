from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.memory import MemoryManager, _mask_pii_exception


def test_mask_pii_exception():
	"""Ensures exception strings are truncated."""
	long_msg = "A" * 200
	ex = Exception(long_msg)
	masked = _mask_pii_exception(ex)
	assert "TRUNCATED" in masked
	assert len(masked) <= 170


def test_add_memory_metadata_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	with pytest.raises(ValueError, match="Invalid engram data"):
		manager.add_memory("col", "text", metadata={"bad": "null\x00byte"})


def test_add_memory_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.upsert.side_effect = Exception("Fail")
	assert manager.add_memory("col", "text") == ""


def test_get_stats_exception_and_success():
	manager = MemoryManager()
	manager.client = MagicMock()

	class MockInfo:
		status = "green"
		points_count = 10
		segments_count = 2

	manager.client.get_collection.return_value = MockInfo()
	stats = manager.get_stats("col")
	assert stats["status"] == "green"
	assert stats["points_count"] == 10
	manager.client.get_collection.side_effect = Exception("DB Fail")
	stats = manager.get_stats("col")
	assert stats["status"] == "error"


def test_trigger_metabolism_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	with patch("threading.Thread") as mock_thread:
		mock_thread.side_effect = Exception("Thread limit reached")
		manager._trigger_metabolism()
		assert True


def test_reinforce_points_empty_and_payload_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	assert manager._reinforce_points("col", [], {}) == []
	manager._reinforce_points("col", ["not-uuid"], {"not-uuid": 0.1})

	class MockPoint:
		def __init__(self):
			self.id = "1"
			self.payload = {"reinforcement_score": 1.0}

	manager.client.retrieve.return_value = [MockPoint()]
	manager.client.batch_update_points.side_effect = Exception("Payload Set Fail")
	points = manager._reinforce_points("col", [1], {1: 0.1})  # type: ignore
	assert len(points) == 0


def test_reinforce_points_retrieve_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.retrieve.side_effect = Exception("Retrieve error")
	assert manager._reinforce_points("col", [1], {1: 0.1}) == []  # type: ignore


@patch("red_pill.memory.MemoryManager._get_vector", return_value=[0.1])
def test_search_and_reinforce_query_exception(mock_vec):
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.query_points.side_effect = Exception("Search fail")
	results = manager.search_and_reinforce("col", "query")
	assert results == []


def test_calculate_decay_edge_cases():
	manager = MemoryManager()
	monkeypatch = pytest.MonkeyPatch()
	monkeypatch.setattr(cfg, "DECAY_STRATEGY", "exponential")
	val = manager._calculate_decay(-0.5, 0.1)
	assert val == 0.0
	monkeypatch.setattr(cfg, "DECAY_STRATEGY", "unknown")
	val = manager._calculate_decay(5.0, 0.1)
	assert val == 4.9


def test_apply_erosion_exceptions_and_deletions():
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.scroll.side_effect = Exception("Scroll Failed")
	cfg.METABOLISM_ENABLED = True
	manager.apply_erosion("col")
	manager.apply_erosion("col", -0.1)
	manager.client.scroll.side_effect = None
	manager.client.scroll.return_value = ([], None)
	manager.apply_erosion("col")

	class MockPoint:
		def __init__(self, _id, score, immune):
			self.id = _id
			self.payload = {"content": "text", "reinforcement_score": score, "immune": immune}

	p1 = MockPoint("1", 1.0, True)
	p2 = MockPoint("2", 1.0, False)
	p3 = MockPoint("3", 2.0, False)
	manager.client.scroll.return_value = ([p1, p2, p3], None)
	manager.client.batch_update_points.side_effect = Exception("Set Payload Failed")
	manager.client.delete.side_effect = Exception("Delete Failed")
	cfg.METABOLISM_COOLDOWN = 3600
	manager.apply_erosion("col", 1.0)


def test_sanitize_exceptions():
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.scroll.side_effect = Exception("Scroll Failed")
	res = manager.sanitize("col")
	assert res["duplicates_found"] == 0

	class MockPoint:
		def __init__(self):
			self.id = "1"
			self.payload = {
				"content": "text",
				"reinforcement_score": 1.0,
				"importance": 1.0,
				"created_at": 1000.0,
				"last_recalled_at": 1000.0,
				"schema_version": "v1.0",
			}

	manager.client.scroll.side_effect = None
	manager.client.scroll.return_value = ([MockPoint()], None)
	manager.client.batch_update_points.side_effect = Exception("Set Payload Failed")
	manager.sanitize("col")
	manager.client.batch_update_points.side_effect = None
	res = manager.sanitize("col", dry_run=True)
	assert res["migrated_records"] == 1
	seen_mock1 = MockPoint()
	seen_mock2 = MockPoint()
	seen_mock2.id = "2"
	seen_mock2.payload = {"content": "text"}
	manager.client.scroll.return_value = ([seen_mock1, seen_mock2], None)
	manager.client.batch_update_points.side_effect = None
	manager.client.delete.side_effect = Exception("Delete Failed")
	res = manager.sanitize("col")
	assert res["duplicates_found"] == 1
