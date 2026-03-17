from unittest.mock import MagicMock, patch

import pytest

from red_pill.memory import MemoryManager


@pytest.fixture
def mem_mgr():
	with patch("red_pill.memory.QdrantClient"):
		with patch("red_pill.memory.cfg") as mock_cfg:
			mock_cfg.MAX_AXONS = 5
			mock_cfg.PROPAGATION_FACTOR = 0.5
			mm = MemoryManager()
			yield mm


def test_dream_success(mem_mgr):
	mock_point = MagicMock()
	mock_point.id = "1"
	mock_point.payload = {"content": "dreamy thoughts", "associations": []}
	mock_point.vector = [0.1] * 384
	mem_mgr.client.scroll.return_value = ([mock_point], None)
	mock_hit = MagicMock()
	mock_hit.id = "2"
	mock_hit.score = 0.95
	mem_mgr.client.query_points.return_value = MagicMock(points=[mock_hit])
	mem_mgr.dream("work_memories")
	assert mem_mgr.client.set_payload.called
	args = mem_mgr.client.set_payload.call_args[1]
	assert "2" in args["payload"]["associations"]


def test_dream_no_engrams(mem_mgr):
	mem_mgr.client.scroll.return_value = ([], None)
	mem_mgr.dream("work_memories")
	assert not mem_mgr.client.query_points.called


def test_dream_max_axons_reached(mem_mgr):
	mock_point = MagicMock()
	mock_point.id = "1"
	mock_point.payload = {"content": "full", "associations": ["a", "b", "c", "d", "e"]}
	mock_point.vector = [0.1] * 384
	mem_mgr.client.scroll.return_value = ([mock_point], None)
	mock_hit = MagicMock()
	mock_hit.id = "2"
	mock_hit.score = 0.95
	mem_mgr.client.query_points.return_value = MagicMock(points=[mock_hit])
	mem_mgr.dream("work_memories")
	args = mem_mgr.client.set_payload.call_args[1]
	assert len(args["payload"]["associations"]) == 5
	assert "2" in args["payload"]["associations"]
	assert "a" not in args["payload"]["associations"]


def test_dream_search_failure(mem_mgr):
	mock_point = MagicMock()
	mock_point.id = "1"
	mock_point.payload = {"content": "error test"}
	mock_point.vector = [0.1] * 384
	mem_mgr.client.scroll.return_value = ([mock_point], None)
	mem_mgr.client.query_points.side_effect = Exception("Search Fail")
	mem_mgr.dream("work_memories")
	assert not mem_mgr.client.set_payload.called


def test_dream_update_failure(mem_mgr):
	mock_point = MagicMock()
	mock_point.id = "1"
	mock_point.payload = {"content": "update error"}
	mock_point.vector = [0.1] * 384
	mem_mgr.client.scroll.return_value = ([mock_point], None)
	mock_hit = MagicMock()
	mock_hit.id = "2"
	mock_hit.score = 0.95
	mem_mgr.client.query_points.return_value = MagicMock(points=[mock_hit])
	mem_mgr.client.set_payload.side_effect = Exception("Update Fail")
	mem_mgr.dream("work_memories")
	assert mem_mgr.client.set_payload.called


def test_dream_invalid_point(mem_mgr):
	mock_point = MagicMock()
	mock_point.vector = None
	mem_mgr.client.scroll.return_value = ([mock_point], None)
	mem_mgr.dream("work_memories")
	assert not mem_mgr.client.query_points.called
