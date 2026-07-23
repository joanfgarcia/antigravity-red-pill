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


@patch("red_pill.metabolism.phases.consolidation.distill_session_anchors")
@patch("red_pill.metabolism.phases.consolidation.distill_engram")
@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
def test_perform_sleep_cycle(mock_llm, mock_distill, mock_anchors):
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
	assert res2["emotion"] == "neutral"  # V3: values outside the closed taxonomy normalize to neutral
	assert res2["intensity"] == 0.5
	assert res2["category"] == "social"  # fallback_category is social


def test_chunk_text_runt_absorption():
	# A trailing shard under 15% of size folds into the previous chunk
	text = ("A" * 490 + ". ") + ("B" * 480 + ". ") + "tail..."
	chunks = chunk_text(text, size=500)
	assert "".join(chunks) == text
	assert len(chunks[-1]) >= 500 * 0.15 or len(chunks) == 1
	assert chunks[-1].endswith("tail...")


def test_chunk_text_runt_single_chunk_untouched():
	# A single short text is never "absorbed" into nothing
	assert chunk_text("tiny", size=500) == ["tiny"]


def test_reassemble_raw_sequence():
	from red_pill.metabolism.phases.consolidation import reassemble_raw_sequence

	mock_client = MagicMock()
	p0 = MagicMock(
		id="p0",
		payload={"parent_id": "seq-123", "lazarus_phase": "raw_parent", "chunk_index": 0, "content": "USER: Hola Barcelona, estamos en casa de "},
	)
	p1 = MagicMock(id="p1", payload={"parent_id": "seq-123", "lazarus_phase": "raw_parent", "chunk_index": 1, "content": "mi madre Victoria."})

	mock_client.scroll.return_value = ([p1, p0], None)  # out of order return from scroll

	full_text, assembled_points = reassemble_raw_sequence(mock_client, "interaction_memories", p0)

	assert full_text == "USER: Hola Barcelona, estamos en casa de mi madre Victoria."
	assert [p.id for p in assembled_points] == ["p0", "p1"]


def test_emotion_synonyms_normalization():
	from red_pill.core.providers import ProviderRegistry

	mock_inference = ProviderRegistry.get_inference_provider("sip")
	mock_inference.generate.return_value = '{"summary": "test entusiasmo", "emotion": "entusiasmo", "intensity": 0.85, "category": "social"}'  # type: ignore
	res = distill_engram("raw content")
	assert res["emotion"] == "joy"

	mock_inference.generate.return_value = '{"summary": "test ansiedad", "emotion": "ansiedad", "intensity": 0.7, "category": "social"}'  # type: ignore
	res2 = distill_engram("raw content")
	assert res2["emotion"] == "anxiety"


def test_audit_engram_quality():
	from red_pill.metabolism.distiller import audit_engram_quality

	with patch("red_pill.core.providers.ProviderRegistry.get_inference_provider") as mock_prov:
		mock_provider = MagicMock()
		mock_prov.return_value = mock_provider

		# Scenario 1: LLM deems memory clinical/3rd-person -> needs_redistillation = True
		mock_provider.generate.return_value = '{"needs_redistillation": true, "reason": "3rd person clinical observer"}'
		assert audit_engram_quality("Joan informó que...") is True

		# Scenario 2: LLM deems memory clean 1st-person -> needs_redistillation = False
		mock_provider.generate.return_value = '{"needs_redistillation": false, "reason": "Clean 1st-person voice"}'
		assert audit_engram_quality("Me dijiste que en Barcelona estabas de visita...") is False


def test_multi_hub_batching_partitioning():
	import red_pill.config as cfg

	max_chunks_per_hub = getattr(cfg, "SLEEP_MAX_CHUNKS_PER_HUB", 6)
	surviving_chunks = [{"summary": f"Chunk {i}", "emotion": "neutral", "intensity": 0.5, "category": "work"} for i in range(14)]
	fragment_affects = [{"child_id": f"id_{i}", "emotion": "neutral", "intensity": 0.5, "category": "work"} for i in range(14)]

	if len(surviving_chunks) > max_chunks_per_hub:
		chunk_batches = [surviving_chunks[k : k + max_chunks_per_hub] for k in range(0, len(surviving_chunks), max_chunks_per_hub)]
		affects_batches = [fragment_affects[k : k + max_chunks_per_hub] for k in range(0, len(fragment_affects), max_chunks_per_hub)]
	else:
		chunk_batches = [surviving_chunks]
		affects_batches = [fragment_affects]

	assert len(chunk_batches) == 3
	assert len(chunk_batches[0]) == 6
	assert len(chunk_batches[1]) == 6
	assert len(chunk_batches[2]) == 2
	assert len(affects_batches) == 3


def test_cleanup_orphan_raw_parents():
	from red_pill.metabolism.maintenance import cleanup_orphan_raw_parents

	mock_mem_mgr = MagicMock()
	mock_client = mock_mem_mgr.client
	mock_client.collection_exists.return_value = True

	# parent1 has children that no longer exist (retrieve -> [])
	parent1 = MagicMock(id="parent1", payload={"lazarus_phase": "raw_parent", "associations": ["child1", "child2"]})
	mock_client.scroll.side_effect = [([parent1], None), ([], None)]
	mock_client.retrieve.return_value = []

	report = cleanup_orphan_raw_parents(mock_mem_mgr, collections=["work_memories"])
	assert report["work_memories"] == 1
	assert mock_client.delete.called
