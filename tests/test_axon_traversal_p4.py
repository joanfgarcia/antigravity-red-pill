"""P4: typed evocative cascade + traversal reinforcement (ADR-AXON-001 §6)."""

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


def _payload(content: str, **extra):
	return {
		"content": content,
		"importance": 1.0,
		"reinforcement_score": 1.0,
		"created_at": NOW,
		"last_recalled_at": NOW,
		"schema_version": "7",
		"color": "gray",
		"emotion": "neutral",
		"intensity": 1.0,
		"immune": False,
		**extra,
	}


def _put(mm, collection, content, vector, **extra):
	pid = str(uuid.uuid4())
	mm.client.upsert(collection_name=collection, points=[models.PointStruct(id=pid, vector=vector, payload=_payload(content, **extra))])
	return pid


@pytest.fixture()
def mm(memory_manager, monkeypatch):
	monkeypatch.setattr(memory_manager, "_get_vector", lambda text: _vec(0.5))
	monkeypatch.setattr(cfg, "METABOLISM_STRATEGY", "EAGER")  # keep direct-hit decay out of the way
	existing = {c.name for c in memory_manager.client.get_collections().collections}
	for col in ("work_memories", "social_memories"):
		if col not in existing:
			memory_manager.client.create_collection(collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
	return memory_manager


def _seed_pair(mm, weight=0.9):
	social_id = _put(mm, "social_memories", "charla del paseo", _vec(0.9))
	work_id = _put(
		mm,
		"work_memories",
		"decisión del algoritmo",
		_vec(0.5),
		associations=[{"id": social_id, "target_collection": "social_memories", "weight": weight, "association_type": "temporal_semantic"}],
	)
	return social_id, work_id


def test_traversal_injects_with_weight_and_reinforces(mm, monkeypatch):
	monkeypatch.setattr(cfg, "AXON_READ_ENABLED", True)
	social_id, _ = _seed_pair(mm, weight=0.9)

	results = mm.search_and_reinforce("work_memories", "algoritmo", limit=3)
	evoked = [r for r in results if r.payload and r.payload.get("_axon_weight")]
	assert len(evoked) == 1
	assert str(evoked[0].id) == social_id
	assert evoked[0].payload["_is_evoked"] is True
	assert evoked[0].payload["_axon_weight"] == 0.9

	# Traversal reinforcement: W·β landed on the social target via its collection engine
	# (engines update their own state — recall_count/last_recalled_at are the engine-agnostic proof)
	stored = mm.client.retrieve(collection_name="social_memories", ids=[social_id], with_payload=True)[0]
	assert stored.payload.get("recall_count", 0) >= 1
	assert stored.payload["last_recalled_at"] > NOW


def test_flag_off_keeps_axons_dormant(mm, monkeypatch):
	monkeypatch.setattr(cfg, "AXON_READ_ENABLED", False)
	social_id, _ = _seed_pair(mm)

	results = mm.search_and_reinforce("work_memories", "algoritmo", limit=3)
	assert all(str(r.id) != social_id for r in results)
	stored = mm.client.retrieve(collection_name="social_memories", ids=[social_id], with_payload=True)[0]
	assert stored.payload.get("recall_count", 0) == 0  # untouched in shadow mode


def test_top2_by_weight_per_hit(mm, monkeypatch):
	monkeypatch.setattr(cfg, "AXON_READ_ENABLED", True)
	socials = [_put(mm, "social_memories", f"s{i}", _vec(0.9)) for i in range(4)]
	weights = [0.61, 0.95, 0.7, 0.88]
	axons = [
		{"id": sid, "target_collection": "social_memories", "weight": w, "association_type": "temporal_semantic"}
		for sid, w in zip(socials, weights)
	]
	_put(mm, "work_memories", "hub con 4 axones", _vec(0.5), associations=axons)

	results = mm.search_and_reinforce("work_memories", "hub", limit=3)
	evoked_ids = {str(r.id) for r in results if r.payload and r.payload.get("_axon_weight")}
	assert evoked_ids == {socials[1], socials[3]}  # the two heaviest


def test_dangling_target_skipped_gracefully(mm, monkeypatch):
	monkeypatch.setattr(cfg, "AXON_READ_ENABLED", True)
	ghost = str(uuid.uuid4())
	_put(
		mm,
		"work_memories",
		"hub con axón huérfano",
		_vec(0.5),
		associations=[{"id": ghost, "target_collection": "social_memories", "weight": 0.8, "association_type": "temporal_semantic"}],
	)
	results = mm.search_and_reinforce("work_memories", "hub", limit=3)
	assert all(str(r.id) != ghost for r in results)  # no crash, orphan skipped


def test_eroded_target_not_injected(mm, monkeypatch):
	monkeypatch.setattr(cfg, "AXON_READ_ENABLED", True)
	social_id, _ = _seed_pair(mm)

	import red_pill.memory as memory_module

	class _DeadEngine:
		def calculate_lazy_decay(self, payload, current_time):
			return {"_delete": True} if payload.get("content") == "charla del paseo" else {}

		def calculate_reinforcement(self, payload, increment):
			return {}

	monkeypatch.setattr(memory_module, "get_memory_engine", lambda name: _DeadEngine())
	results = mm.search_and_reinforce("work_memories", "algoritmo", limit=3)
	assert all(str(r.id) != social_id for r in results)
