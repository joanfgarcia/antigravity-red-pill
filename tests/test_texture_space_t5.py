"""T5: texture_shadow points + resonance search (implemented, born dark)."""

import time
import uuid

import pytest
from qdrant_client import models

import red_pill.config as cfg

DIM = cfg.VECTOR_SIZE
NOW = time.time()


def _vec(seed: float):
	v = [0.0] * DIM
	v[0] = 1.0
	v[1] = seed
	return v


@pytest.fixture()
def mm(memory_manager, monkeypatch):
	existing = {c.name for c in memory_manager.client.get_collections().collections}
	for col in ("work_memories", "social_memories"):
		if col not in existing:
			memory_manager.client.create_collection(
				collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE)
			)
	monkeypatch.setattr(cfg, "METABOLISM_STRATEGY", "EAGER")
	# deterministic embedder: texture text and resonance query share a vector
	vectors = {"agotados pero contentos": _vec(0.9)}
	monkeypatch.setattr(memory_manager, "_get_vector", lambda text: vectors.get(text, _vec(0.1)))
	return memory_manager


def _put_hub(mm, collection, content):
	pid = str(uuid.uuid4())
	payload = {
		"content": content,
		"importance": 1.0,
		"reinforcement_score": 1.0,
		"created_at": NOW,
		"last_recalled_at": NOW,
		"schema_version": "7",
		"lazarus_phase": "synthesis_hub",
	}
	mm.client.upsert(collection_name=collection, points=[models.PointStruct(id=pid, vector=_vec(0.5), payload=payload)])
	return pid


def test_shadow_idempotent_per_parent(mm):
	hub = _put_hub(mm, "work_memories", "decisión del algoritmo")
	s1 = mm.add_texture_shadow("work_memories", hub, "agotados pero contentos")
	s2 = mm.add_texture_shadow("work_memories", hub, "agotados pero contentos")
	assert s1 == s2  # uuid5 per parent: re-consolidation overwrites, never duplicates


def test_resonance_search_resolves_parent(mm):
	hub = _put_hub(mm, "work_memories", "decisión del algoritmo")
	mm.add_texture_shadow("work_memories", hub, "agotados pero contentos")

	results = mm.search_and_reinforce("work_memories", "agotados pero contentos", search_space="texture", caller="t5")
	assert [str(r.id) for r in results] == [hub]
	assert results[0].payload["_texture_match"] == "agotados pero contentos"
	assert results[0].payload["_texture_score"] > 0.9
	# resonance recall reinforces the parent like any other recall
	stored = mm.client.retrieve(collection_name="work_memories", ids=[hub], with_payload=True)[0]
	assert stored.payload.get("recall_count", 0) >= 1


def test_shadow_excluded_from_factual_search(mm):
	hub = _put_hub(mm, "work_memories", "decisión del algoritmo")
	shadow_id = mm.add_texture_shadow("work_memories", hub, "agotados pero contentos")

	results = mm.search_and_reinforce("work_memories", "agotados pero contentos", search_space="summary", deep_recall=True)
	assert all(str(r.id) != shadow_id for r in results)  # the shadow never leaks into factual space


def test_texture_search_empty_when_no_shadows(mm):
	_put_hub(mm, "work_memories", "sin sombra")
	assert mm.search_and_reinforce("work_memories", "agotados pero contentos", search_space="texture") == []


def test_consolidation_respects_dark_flag(mm):
	# flag off (default): add_texture_shadow is never called by consolidation paths;
	# here we assert the config default itself so a future accidental flip fails loudly.
	assert cfg.TEXTURE_SHADOW_ENABLED is False
