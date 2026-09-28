from unittest.mock import MagicMock, patch

from red_pill.metabolism.sleep import distill_engram, perform_sleep_cycle, synthesize_hub


def test_distill_engram_markdown_cleaning():
	"""Test cleaning of markdown fences from LLM response."""
	mock_provider = MagicMock()
	mock_provider.generate.return_value = '```json\n{"summary": "test", "emotion": "joy", "intensity": 0.9}\n```'

	with patch("red_pill.core.providers.ProviderRegistry.get_inference_provider", return_value=mock_provider):
		result = distill_engram("raw")
	assert result["summary"] == "test"
	assert result["emotion"] == "joy"

	# Second call: backtick-only fence
	mock_provider.generate.return_value = '```\n{"summary": "test2", "emotion": "sadness", "intensity": 0.1}\n```'
	with patch("red_pill.core.providers.ProviderRegistry.get_inference_provider", return_value=mock_provider):
		result = distill_engram("raw")
	assert result["summary"] == "test2"


def test_distill_engram_error_path():
	"""Test fallback on HTTP error or timeout."""
	mock_provider = MagicMock()
	mock_provider.generate.side_effect = Exception("Timeout")
	with patch("red_pill.core.providers.ProviderRegistry.get_inference_provider", return_value=mock_provider):
		result = distill_engram("raw content that is quite long " * 10)
		assert "raw content" in result["summary"]
		assert result["emotion"] == "neutral"


def test_synthesize_hub_error_path():
	"""Test fallback on synthesis failure."""
	mock_opener = MagicMock()
	mock_opener.open.side_effect = Exception("LLM Down")
	with patch("red_pill.metabolism.distiller.urllib.request.build_opener", return_value=mock_opener):
		result = synthesize_hub(["summary 1", "summary 2"])
		assert "Aggregated Memory Sequence" in result


@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
def test_perform_sleep_cycle_collection_missing(mock_llm):
	mock_mgr = MagicMock()
	mock_mgr.client.collection_exists.return_value = False
	result = perform_sleep_cycle(mock_mgr)
	assert result == 0


@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
def test_perform_sleep_cycle_scroll_error(mock_llm):
	mock_mgr = MagicMock()
	mock_mgr.client.collection_exists.return_value = True
	mock_mgr.client.scroll.side_effect = Exception("Qdrant error")
	result = perform_sleep_cycle(mock_mgr)
	assert result == 0
