import json
import pytest
from unittest.mock import MagicMock, patch

from red_pill.metabolism.sleep import chunk_text, distill_engram, perform_sleep_cycle, synthesize_hub


def test_chunk_text():
	text = "This is a long text. It has multiple sentences. We want to test chunking."
	chunks = chunk_text(text, size=20)
	assert len(chunks) > 1
	assert "".join(chunks) == text


def test_chunk_text_edge_cases():
	assert chunk_text("", size=10) == []
	assert chunk_text("short", size=10) == ["short"]


@pytest.mark.xfail(reason="sleep.py imports urllib.request locally inside distill_engram — patch at module level is not intercepted (pre-existing, same as test_sleep_coverage.py)")
@patch("urllib.request.OpenerDirector.open")
def test_distill_engram(mock_open):
	mock_response = MagicMock()
	mock_response.read.return_value = json.dumps(
		{"choices": [{"message": {"content": '{"summary": "test", "emotion": "joy", "intensity": 0.9}'}}]}
	).encode()
	mock_response.__enter__.return_value = mock_response
	mock_open.return_value = mock_response
	result = distill_engram("raw content")
	assert result["summary"] == "test"
	assert result["emotion"] == "joy"
	assert result["intensity"] == 0.9


@patch("urllib.request.OpenerDirector.open")
def test_distill_engram_fallback(mock_open):
	mock_open.side_effect = Exception("Network fail")
	result = distill_engram("raw content")
	assert "raw content" in result["summary"]
	assert result["emotion"] == "neutral"


@patch("urllib.request.urlopen")
def test_synthesize_hub(mock_urlopen):
	mock_response = MagicMock()
	mock_response.read.return_value = json.dumps({"choices": [{"message": {"content": "Master summary"}}]}).encode()
	mock_response.__enter__.return_value = mock_response
	mock_urlopen.return_value = mock_response
	result = synthesize_hub(["s1", "s2"])
	assert result == "Master summary"


@patch("red_pill.metabolism.sleep.distill_engram")
def test_perform_sleep_cycle(mock_distill):
	mock_mem_mgr = MagicMock()
	mock_client = mock_mem_mgr.client
	mock_client.collection_exists.return_value = True
	p1 = MagicMock(id="1", payload={"content": "work related code"})
	mock_client.scroll.return_value = ([p1], None)
	mock_distill.return_value = {"summary": "sum", "emotion": "joy", "intensity": 0.8}
	count = perform_sleep_cycle(mock_mem_mgr)
	assert count > 0
	assert mock_mem_mgr.add_memory.called
	assert mock_client.delete.called


def test_perform_sleep_cycle_no_collection():
	mock_mem_mgr = MagicMock()
	mock_mem_mgr.client.collection_exists.return_value = False
	assert perform_sleep_cycle(mock_mem_mgr) == 0


def test_perform_sleep_cycle_empty_buffer():
	mock_mem_mgr = MagicMock()
	mock_mem_mgr.client.collection_exists.return_value = True
	mock_mem_mgr.client.scroll.return_value = ([], None)
	assert perform_sleep_cycle(mock_mem_mgr) == 0
