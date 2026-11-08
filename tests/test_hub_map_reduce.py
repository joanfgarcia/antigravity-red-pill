"""Hub synthesis map-reduce: fin del truncado + navegación del detalle."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import red_pill.config as cfg
from red_pill.metabolism.distiller import (
	hub_budget,
	partition_hub_items,
	render_hub_items,
	synthesize_hub_v2,
)


class _FakeProvider:
	"""Fake SIP provider: registra los prompts y devuelve JSON HUB_V2 válido."""

	def __init__(self, fail=(), summary_len: int = 60):
		self.prompts: list[str] = []
		self.fail = set(fail)
		self.summary_len = summary_len

	def generate(self, prompt, messages=None, temperature=0.1, **kwargs):  # noqa: ANN001
		index = len(self.prompts)
		self.prompts.append(str(prompt))
		if index in self.fail:
			raise RuntimeError("llm down (test)")
		return json.dumps(
			{
				"title": f"Parte {index}",
				"summary": f"S{index} " + ("x" * self.summary_len),
				"texture": f"textura {index}",
				"lang": "es",
			}
		)


def _patch_provider(monkeypatch, provider):
	from red_pill.core import providers

	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: provider))


def _configure(monkeypatch, budget: int = 1200, enabled: bool = True, max_chunks: int = 4):
	monkeypatch.setattr(cfg, "SLEEP_MAX_HUB_INPUT_CHARS", budget, raising=False)
	monkeypatch.setattr(cfg, "SLEEP_HUB_MAP_REDUCE_ENABLED", enabled, raising=False)
	monkeypatch.setattr(cfg, "SLEEP_HUB_MAX_CHUNKS_PER_BATCH", max_chunks, raising=False)
	# El fallback legacy hace HTTP real; en tests siempre mecánico.
	monkeypatch.setattr("red_pill.metabolism.distiller.synthesize_hub", lambda summaries: "fallback mecánico")


def _chunks(n: int, size: int = 200):
	return [
		{
			"summary": f"fragmento {i} " + ("y" * size),
			"texture": f"atmósfera {i}",
			"emotion": "neutral",
			"intensity": 0.5,
			"lang": "es",
		}
		for i in range(n)
	]


def test_texture_dict_is_rendered_as_text():
	text = render_hub_items([{"summary": "a", "texture": {"theme": "complejidad", "relics": ["r1", "r2"]}, "lang": "es"}])
	assert "theme: complejidad" in text
	assert "relics: r1; r2" in text
	assert "{'theme'" not in text


def test_partition_respects_budget_and_keeps_every_item():
	chunks = [{"summary": f"c{i} " + ("z" * 180), "texture": "", "lang": "es"} for i in range(14)]
	batches = partition_hub_items(chunks, 500, 4)
	assert sum(len(b) for b in batches) == 14
	assert all(len(render_hub_items(b)) <= 500 for b in batches)
	assert max(len(b) for b in batches) <= 4


def test_oversized_single_item_is_segmented_not_dropped():
	giant = {"summary": "frase. " * 400, "texture": "atmósfera", "lang": "es"}
	batches = partition_hub_items([giant], 500, 0)
	assert len(batches) > 1
	assert all(len(render_hub_items(b)) <= 500 for b in batches)
	assert sum(len(b[0]["summary"]) for b in batches) >= len(giant["summary"]) - 10


def test_single_batch_keeps_legacy_single_call(monkeypatch):
	_configure(monkeypatch, budget=8000)
	provider = _FakeProvider()
	_patch_provider(monkeypatch, provider)
	hub = synthesize_hub_v2(_chunks(2, 30))
	assert len(provider.prompts) == 1
	assert not hub.get("hierarchical")
	assert hub["truncated"] is False


def test_map_reduce_no_truncation_and_partitions(monkeypatch):
	_configure(monkeypatch, budget=1200)
	provider = _FakeProvider()
	_patch_provider(monkeypatch, provider)
	hub = synthesize_hub_v2(_chunks(10, 200))
	assert hub.get("hierarchical") is True
	assert hub["truncated"] is False
	assert hub["partition_count"] > 1
	assert len(hub["partitions"]) == hub["partition_count"]
	assert [p["index"] for p in hub["partitions"]] == list(range(1, hub["partition_count"] + 1))
	assert len(provider.prompts) > 1
	assert max(len(p) for p in provider.prompts) <= 1200


def test_map_reduce_needs_multiple_reduce_levels(monkeypatch):
	_configure(monkeypatch, budget=1200)
	provider = _FakeProvider(summary_len=500)
	_patch_provider(monkeypatch, provider)
	hub = synthesize_hub_v2(_chunks(10, 200))
	assert hub.get("hierarchical") is True
	assert hub["map_reduce_levels"] >= 1


def test_partial_failure_falls_back_to_mechanical_without_losing_the_cycle(monkeypatch):
	_configure(monkeypatch, budget=1200)
	provider = _FakeProvider(fail={0})
	_patch_provider(monkeypatch, provider)
	hub = synthesize_hub_v2(_chunks(10, 200))
	assert hub.get("_is_fallback") is not True
	assert hub["truncated"] is False
	# La parte 0 cayó al resumen mecánico; el resto se sintetizó.
	assert hub["partitions"][0]["summary"]


def test_final_failure_returns_legacy_fallback(monkeypatch):
	_configure(monkeypatch, budget=1200)
	provider = _FakeProvider(fail=range(1000))
	_patch_provider(monkeypatch, provider)
	hub = synthesize_hub_v2(_chunks(10, 200))
	assert hub["_is_fallback"] is True


def test_no_truncation_warning_when_map_reduce_is_on(monkeypatch, caplog):
	_configure(monkeypatch, budget=1200)
	_patch_provider(monkeypatch, _FakeProvider())
	caplog.set_level(logging.WARNING, logger="red_pill.metabolism.distiller")
	synthesize_hub_v2(_chunks(10, 200))
	assert not any("Truncating user prompt" in r.getMessage() for r in caplog.records)


def test_budget_is_declared_and_configurable(monkeypatch):
	monkeypatch.setattr(cfg, "SLEEP_MAX_HUB_INPUT_CHARS", 12345, raising=False)
	assert hub_budget() == 12345


def test_members_to_chunks_texture_is_text_not_dict():
	from red_pill.metabolism.hub_synthesis import members_to_chunks

	chunks = members_to_chunks([("id1", {"content": "x", "theme": "t", "relics": ["r1"], "session_id": "s"})])
	assert chunks[0]["texture"] == "theme: t | relics: r1"
	assert chunks[0]["relics"] == ["r1"]


def test_force_bypasses_idempotency_but_normal_path_skips(monkeypatch):
	from red_pill.metabolism.hub_synthesis import _synthesize_one, hub_input_hash

	memory = MagicMock()
	memory.client.retrieve.return_value = [MagicMock(payload={"hub_input_hash": hub_input_hash(["m1"])})]
	memory.add_memory.return_value = "hub1"
	memory.client.scroll.return_value = ([], None)
	members = [("m1", {"content": "x", "session_id": "s", "created_at": 1.0})]
	synth = MagicMock(return_value={"title": "t", "summary": "s"})
	affect = lambda chunks: ("neutral", 0.5)  # noqa: E731

	assert _synthesize_one(memory, "work_memories", "s", members, synth, affect, force=False) == "skipped"
	assert synth.call_count == 0
	assert _synthesize_one(memory, "work_memories", "s", members, synth, affect, force=True) == "written"
	assert synth.call_count == 1


def test_hierarchical_metadata_is_persisted_in_the_hub(monkeypatch):
	from red_pill.metabolism.hub_synthesis import _synthesize_one

	memory = MagicMock()
	memory.add_memory.return_value = "hub1"
	memory.client.scroll.return_value = ([], None)
	members = [("m1", {"content": "x", "session_id": "s", "created_at": 1.0})]
	partitions = [{"index": 1, "total": 2, "summary": "p1", "texture": "", "lang": "es"}]
	synth = MagicMock(
		return_value={
			"title": "t",
			"summary": "s",
			"hierarchical": True,
			"partition_count": 2,
			"partitions": partitions,
			"map_reduce_levels": 1,
			"truncated": False,
			"input_chars": 123,
		}
	)
	affect = lambda chunks: ("neutral", 0.5)  # noqa: E731
	assert _synthesize_one(memory, "work_memories", "s", members, synth, affect, force=True) == "written"
	metadata = memory.add_memory.call_args.kwargs["metadata"]
	assert metadata["hub_hierarchical"] is True
	assert metadata["hub_partition_count"] == 2
	assert metadata["hub_partitions"] == partitions
	assert metadata["hub_map_reduce_levels"] == 1
	assert metadata["hub_truncated"] is False
	assert metadata["hub_synth_version"] == 2


def test_find_oversized_sessions_skips_already_remediated():
	from red_pill.metabolism.hub_synthesis import find_oversized_sessions

	point_a = MagicMock(id="a", payload={"content": "x" * 200, "session_id": "s1", "node_type": "memento_engram"})
	point_b = MagicMock(id="b", payload={"content": "y" * 200, "session_id": "s1", "node_type": "memento_engram"})
	memory = MagicMock()
	memory.client.collection_exists.return_value = True
	memory.client.scroll.return_value = ([point_a, point_b], None)
	memory.client.retrieve.return_value = [MagicMock(payload={"hub_synth_version": 2, "hub_truncated": False})]

	assert find_oversized_sessions(memory, collections=("work_memories",), budget=100) == []
	all_rows = find_oversized_sessions(memory, collections=("work_memories",), budget=100, only_pending=False)
	assert len(all_rows) == 1 and all_rows[0]["session_id"] == "s1"

	# Sin hub (pendiente) sí entra aunque only_pending=True.
	memory.client.retrieve.return_value = []
	assert len(find_oversized_sessions(memory, collections=("work_memories",), budget=100)) == 1


def test_hub_partitions_pass_schema_validation():
	"""El esquema de metadata acepta hub_partitions (dicts planos) y rechaza anidados."""
	from red_pill.schemas import CreateEngramRequest

	req = CreateEngramRequest(
		content="x",
		metadata={"hub_partitions": [{"index": 1, "total": 2, "summary": "s", "texture": "", "lang": "es"}]},
	)
	assert req.metadata["hub_partitions"][0]["index"] == 1
	try:
		CreateEngramRequest(content="x", metadata={"hub_partitions": [{"nested": {"x": 1}}]})
	except ValueError:
		pass
	else:
		raise AssertionError("hub_partitions debe rechazar valores anidados")
