import pytest
from unittest.mock import MagicMock, patch
from red_pill.memory import MemoryManager

@pytest.fixture
def mem_mgr():
    with patch("red_pill.memory.QdrantClient"):
        with patch("red_pill.memory.cfg") as mock_cfg:
            mock_cfg.MAX_AXONS = 5
            mm = MemoryManager()
            yield mm

def test_dream_scroll_failure(mem_mgr):
    # Coverage for lines 733-735: Exception during scroll
    mem_mgr.client.scroll.side_effect = Exception("Scroll Hard Fail")
    result = mem_mgr.dream("work_memories")
    assert result["status"] == "error"
    assert "Scroll Hard Fail" in result["message"]

def test_dream_empty_points(mem_mgr):
    # Coverage for line 739: No points found
    mem_mgr.client.scroll.return_value = ([], None)
    result = mem_mgr.dream("work_memories")
    assert result["status"] == "empty"

def test_dream_search_failure_loop(mem_mgr):
    # Coverage for line 760: Exception during query_points for a specific point
    mock_point = MagicMock(id="1", payload={"content": "x"}, vector=[0.1])
    mem_mgr.client.scroll.return_value = ([mock_point], None)
    mem_mgr.client.query_points.side_effect = Exception("Search Fail")
    
    result = mem_mgr.dream("work_memories")
    assert result["status"] == "ok" # Should continue loop
    assert result["synapses"] == 0

def test_dream_set_payload_failure(mem_mgr):
    # Coverage for line 784: Exception during set_payload
    mock_point = MagicMock(id="1", payload={"content": "x", "associations": []}, vector=[0.1])
    mem_mgr.client.scroll.return_value = ([mock_point], None)
    
    partner = MagicMock(id="2", score=0.99)
    mem_mgr.client.query_points.return_value = MagicMock(points=[partner])
    
    mem_mgr.client.set_payload.side_effect = Exception("Payload Fail")
    result = mem_mgr.dream("work_memories")
    assert result["status"] == "ok"
    assert result["synapses"] == 0 # Failed to create synapse
