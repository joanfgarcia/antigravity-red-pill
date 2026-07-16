import json
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


def test_distill_engram():
	from red_pill.core.providers import ProviderRegistry

	mock_inference = ProviderRegistry.get_inference_provider("sip")
	mock_inference.generate.return_value = '{"summary": "test", "emotion": "joy", "intensity": 0.9}'  # type: ignore
	result = distill_engram("raw content")
	assert result["summary"] == "test"
	assert result["emotion"] == "joy"
	assert result["intensity"] == 0.9


def test_distill_engram_fallback():
	from red_pill.core.providers import ProviderRegistry

	mock_inference = ProviderRegistry.get_inference_provider("sip")
	mock_inference.generate.side_effect = Exception("Network fail")  # type: ignore
	result = distill_engram("raw content")
	assert "raw content" in result["summary"]
	assert result["emotion"] == "neutral"


@patch("red_pill.metabolism.distiller.urllib.request.build_opener")
def test_synthesize_hub(mock_build_opener):
	mock_opener = MagicMock()
	mock_response = MagicMock()
	mock_response.read.return_value = json.dumps(
		{"choices": [{"message": {"content": "[TreeKEM Fix] Arreglado el leaf_index omitido en el hash del árbol."}}]}
	).encode()
	mock_response.__enter__.return_value = mock_response
	mock_opener.open.return_value = mock_response
	mock_build_opener.return_value = mock_opener
	result = synthesize_hub(["s1", "s2"])
	assert result == "[TreeKEM Fix] Arreglado el leaf_index omitido en el hash del árbol."


@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
@patch("red_pill.metabolism.phases.consolidation.distill_engram")
def test_perform_sleep_cycle(mock_distill, mock_llm):
	mock_mem_mgr = MagicMock()
	mock_client = mock_mem_mgr.client
	mock_client.collection_exists.return_value = True
	p1 = MagicMock(id="1", payload={"content": "work related code"})
	# First scroll is for signals, second for interactions, third for end of loop
	mock_client.scroll.side_effect = [([], None), ([p1], None), ([], None)]
	mock_distill.return_value = {"summary": "sum", "emotion": "joy", "intensity": 0.8}
	count = perform_sleep_cycle(mock_mem_mgr)
	assert count > 0
	assert mock_mem_mgr.add_memory.called
	assert mock_client.delete.called


@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
def test_perform_sleep_cycle_no_collection(mock_llm):
	mock_mem_mgr = MagicMock()
	mock_mem_mgr.client.collection_exists.return_value = False
	assert perform_sleep_cycle(mock_mem_mgr) == 0


@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
def test_perform_sleep_cycle_empty_buffer(mock_llm):
	mock_mem_mgr = MagicMock()
	mock_mem_mgr.client.collection_exists.return_value = True
	mock_mem_mgr.client.scroll.return_value = ([], None)
	assert perform_sleep_cycle(mock_mem_mgr) == 0


def test_detect_category_heuristics_non_string():
	from red_pill.metabolism.sleep import detect_category_heuristics

	assert detect_category_heuristics({"some": "dict"}) == "social"
	assert detect_category_heuristics(12.34) == "social"
	assert detect_category_heuristics("```python\nprint(1)```") == "work"


def test_distill_engram_malformed_json_types():
	from red_pill.core.providers import ProviderRegistry

	mock_inference = ProviderRegistry.get_inference_provider("sip")

	# Scenario 1: emotion is a dict, intensity is a dict, category is a dict
	mock_inference.generate.return_value = (
		'{"summary": "dict test", "emotion": {"type": "joy"}, "intensity": {"value": 0.95}, "category": {"name": "work"}}'  # type: ignore
	)
	res1 = distill_engram("raw content")
	assert res1["summary"] == "dict test"
	assert res1["emotion"] == "joy"
	assert res1["intensity"] == 0.95
	assert res1["category"] == "work"

	# Scenario 2: emotion is a float, category is None
	mock_inference.generate.return_value = '{"summary": "float test", "emotion": 12.3, "intensity": "invalid", "category": null}'  # type: ignore
	res2 = distill_engram("raw content")
	assert res2["summary"] == "float test"
	assert res2["emotion"] == "12.3"
	assert res2["intensity"] == 0.5
	assert res2["category"] == "social"  # fallback_category is social
