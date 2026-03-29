import json
from unittest.mock import MagicMock, patch

from red_pill.metabolism.sleep import distill_engram, perform_sleep_cycle, synthesize_hub


def test_distill_engram_markdown_cleaning():
	"""Test cleaning of markdown fences from LLM response."""
	mock_resp = MagicMock()
	mock_resp.read.return_value = json.dumps(
		{"choices": [{"message": {"content": '```json\n{"summary": "test", "emotion": "joy", "intensity": 0.9}\n```'}}]}
	).encode()
	mock_resp.__enter__.return_value = mock_resp
	mock_resp.__exit__.return_value = False
	mock_opener = MagicMock()
	mock_opener.open.return_value = mock_resp

	with (
		patch("red_pill.metabolism.sleep.os.path.exists", return_value=False),
		patch("red_pill.metabolism.sleep.urllib.request.build_opener", return_value=mock_opener),
	):
		result = distill_engram("raw")
	assert result["summary"] == "test"
	assert result["emotion"] == "joy"

	# Second call: backtick-only fence
	mock_resp.read.return_value = json.dumps(
		{"choices": [{"message": {"content": '```\n{"summary": "test2", "emotion": "sadness", "intensity": 0.1}\n```'}}]}
	).encode()
	with (
		patch("red_pill.metabolism.sleep.os.path.exists", return_value=False),
		patch("red_pill.metabolism.sleep.urllib.request.build_opener", return_value=mock_opener),
	):
		result = distill_engram("raw")
	assert result["summary"] == "test2"


def test_distill_engram_error_path():
	"""Test fallback on HTTP error or timeout."""
	mock_opener = MagicMock()
	mock_opener.open.side_effect = Exception("Timeout")
	with (
		patch("red_pill.metabolism.sleep.os.path.exists", return_value=False),
		patch("red_pill.metabolism.sleep.urllib.request.build_opener", return_value=mock_opener),
	):
		result = distill_engram("raw content that is quite long " * 10)
		assert "raw content" in result["summary"]
		assert result["emotion"] == "neutral"


def test_synthesize_hub_error_path():
	"""Test fallback on synthesis failure."""
	with patch("red_pill.metabolism.sleep.urllib.request.urlopen", side_effect=Exception("LLM Down")):
		result = synthesize_hub(["summary 1", "summary 2"])
		assert "Aggregated Memory Sequence" in result


def test_perform_sleep_cycle_collection_missing():
	mock_mgr = MagicMock()
	mock_mgr.client.collection_exists.return_value = False
	result = perform_sleep_cycle(mock_mgr)
	assert result == 0


def test_perform_sleep_cycle_scroll_error():
	mock_mgr = MagicMock()
	mock_mgr.client.collection_exists.return_value = True
	mock_mgr.client.scroll.side_effect = Exception("Qdrant error")
	result = perform_sleep_cycle(mock_mgr)
	assert result == 0


def test_perform_sleep_cycle_affective_culling():
	"""Test that neutral/low-intensity chunks are culled if multiple chunks exist."""
	mock_mgr = MagicMock()
	mock_mgr.client.collection_exists.return_value = True
	point = MagicMock()
	point.id = "idx-1"
	point.payload = {"content": "Normal sentence. Another sentence. Boring stuff."}
	mock_mgr.client.scroll.return_value = ([point], None)
	with patch("red_pill.metabolism.sleep._check_llm_available", return_value=True):
		with patch("red_pill.metabolism.sleep.chunk_text", return_value=["Boring part", "Interesting part"]):
			with patch("red_pill.metabolism.sleep.distill_engram") as mock_distill:
				mock_distill.side_effect = [
					{"summary": "boring", "emotion": "neutral", "intensity": 0.1},
					{"summary": "interesting", "emotion": "joy", "intensity": 0.8},
				]
				with patch("red_pill.metabolism.sleep.synthesize_hub", return_value="master summary"):
					from unittest.mock import ANY

					result = perform_sleep_cycle(mock_mgr)
					assert result >= 1
					mock_mgr.add_memory.assert_any_call(
						collection="social_memories", text="interesting", metadata=ANY, color="purple", emotion="joy", intensity=0.8
					)


def test_perform_sleep_cycle_fixate_error():
	"""Test error handling when writing to Qdrant fails during cycle."""
	mock_mgr = MagicMock()
	mock_mgr.client.collection_exists.return_value = True
	point = MagicMock()
	point.id = "idx-1"
	point.payload = {"content": "some content"}
	mock_mgr.client.scroll.return_value = ([point], None)
	with patch("red_pill.metabolism.sleep._check_llm_available", return_value=True):
		with patch("red_pill.metabolism.sleep.distill_engram", return_value={"summary": "s", "emotion": "e", "intensity": 0.5}):
			mock_mgr.add_memory.side_effect = Exception("Write failed")
			result = perform_sleep_cycle(mock_mgr)
			assert result == 0
			# Raw node must NOT be deleted since nothing was saved
			mock_mgr.client.delete.assert_not_called()
