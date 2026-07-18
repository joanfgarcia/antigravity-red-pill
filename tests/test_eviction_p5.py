"""P5: ARCH-002 eviction resolves target significance per collection."""

import time
import uuid

import pytest
from qdrant_client import models

import red_pill.config as cfg

DIM = cfg.VECTOR_SIZE
NOW = time.time()


def _put(mm, collection, importance, reinforcement):
	pid = str(uuid.uuid4())
	payload = {
		"content": "x",
		"importance": importance,
		"reinforcement_score": reinforcement,
		"created_at": NOW,
		"last_recalled_at": NOW,
		"schema_version": "7",
	}
	vec = [1.0] + [0.0] * (DIM - 1)
	mm.client.upsert(collection_name=collection, points=[models.PointStruct(id=pid, vector=vec, payload=payload)])
	return pid


@pytest.fixture()
def mm(memory_manager):
	existing = {c.name for c in memory_manager.client.get_collections().collections}
	for col in ("work_memories", "social_memories"):
		if col not in existing:
			memory_manager.client.create_collection(
				collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE)
			)
	return memory_manager


def test_cross_axon_not_misread_as_dead_link(mm, monkeypatch):
	monkeypatch.setattr(cfg, "MAX_AXONS", 2)
	# Strong cross target (in the OTHER collection) + one weak and one strong local
	strong_cross = _put(mm, "social_memories", 5.0, 3.0)
	weak_local = _put(mm, "work_memories", 0.1, 0.1)
	strong_local = _put(mm, "work_memories", 5.0, 3.0)

	assocs = [
		{"id": strong_cross, "target_collection": "social_memories", "weight": 0.9, "association_type": "temporal_semantic"},
		weak_local,
		strong_local,
	]
	kept = mm._symmetric_axons_eviction("work_memories", assocs)
	kept_ids = [a["id"] if isinstance(a, dict) else str(a) for a in kept]
	assert len(kept) == 2
	assert strong_cross in kept_ids  # the bridge survives: scored in its own collection
	assert weak_local not in kept_ids


def test_true_dead_link_still_evicted_first(mm, monkeypatch):
	monkeypatch.setattr(cfg, "MAX_AXONS", 2)
	ghost = str(uuid.uuid4())  # points nowhere in any collection
	alive_a = _put(mm, "work_memories", 3.0, 2.0)
	alive_b = _put(mm, "social_memories", 3.0, 2.0)

	assocs = [
		ghost,
		alive_a,
		{"id": alive_b, "target_collection": "social_memories", "weight": 0.7, "association_type": "temporal_semantic"},
	]
	kept = mm._symmetric_axons_eviction("work_memories", assocs)
	kept_ids = [a["id"] if isinstance(a, dict) else str(a) for a in kept]
	assert ghost not in kept_ids
