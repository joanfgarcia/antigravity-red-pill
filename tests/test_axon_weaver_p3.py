"""P3: AxonWeaver integration against in-memory Qdrant (ADR-AXON-001 §7 tests)."""

import time
import uuid
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient, models

import red_pill.config as cfg
from red_pill.metabolism.axons import (
	SOURCE_COLLECTION,
	TARGET_COLLECTION,
	compute_axon_weight,
	weave_cross_axons,
)
from red_pill.schemas import normalize_associations

DIM = 8  # small vectors: similarity is what matters, not the embedder


@pytest.fixture()
def client():
	c = QdrantClient(":memory:")
	for col in (SOURCE_COLLECTION, TARGET_COLLECTION):
		c.create_collection(collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
	return c


def _mm(client):
	return SimpleNamespace(client=client)


def _put(client, collection, vector, created_at, payload_extra=None):
	pid = str(uuid.uuid4())
	payload = {"content": "x", "created_at": created_at, **(payload_extra or {})}
	client.upsert(collection_name=collection, points=[models.PointStruct(id=pid, vector=vector, payload=payload)])
	return pid


def _cross_axons(client, collection, pid):
	payload = client.retrieve(collection_name=collection, ids=[pid], with_payload=True)[0].payload
	return [a for a in normalize_associations(payload.get("associations", [])) if a.is_cross(collection)]


NOW = time.time()
V_SIMILAR_A = [1.0, 0.8, 0.0, 0.0, 0.1, 0.0, 0.0, 0.0]
V_SIMILAR_B = [1.0, 0.7, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0]  # cos ≈ 0.99 with A
V_ORTHOGONAL = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0]


def test_adr_case_walk_and_algorithm(client):
	"""Two memories 1h apart with moderate-high similarity connect symmetrically."""
	social = _put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600)
	work = _put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 7200)  # 1h before social

	stats = weave_cross_axons(_mm(client))
	assert stats["axons_woven"] == 1

	social_axons = _cross_axons(client, SOURCE_COLLECTION, social)
	work_axons = _cross_axons(client, TARGET_COLLECTION, work)
	assert [a.id for a in social_axons] == [work]
	assert [a.id for a in work_axons] == [social]
	expected_w = compute_axon_weight(0.99, 3600)
	assert abs(social_axons[0].weight - expected_w) < 0.02
	assert social_axons[0].association_type == "temporal_semantic"


def test_orthogonal_or_distant_pairs_do_not_connect(client):
	social = _put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600)
	_put(client, TARGET_COLLECTION, V_ORTHOGONAL, NOW - 3600)  # same time, no similarity
	_put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 3600 - cfg.AXON_DT_MAX_HOURS * 3600 - 60)  # similar, outside Δt

	stats = weave_cross_axons(_mm(client))
	assert stats["axons_woven"] == 0
	assert _cross_axons(client, SOURCE_COLLECTION, social) == []


def test_idempotent_reweave(client):
	_put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600)
	work = _put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 7200)

	weave_cross_axons(_mm(client))
	stats2 = weave_cross_axons(_mm(client))
	assert stats2["axons_woven"] == 0  # dedupe by target id
	assert len(_cross_axons(client, TARGET_COLLECTION, work)) == 1


def test_repair_heals_one_way_link(client):
	social = _put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600)
	work = _put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 7200)
	weave_cross_axons(_mm(client))
	# simulate the mid-write failure: strip the work-side axon
	client.set_payload(collection_name=TARGET_COLLECTION, payload={"associations": []}, points=[work])
	assert _cross_axons(client, TARGET_COLLECTION, work) == []

	stats = weave_cross_axons(_mm(client))
	assert stats["axons_repaired"] >= 1
	assert [a.id for a in _cross_axons(client, TARGET_COLLECTION, work)] == [social]


def test_dangling_axon_gc(client):
	social = _put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600)
	work = _put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 7200)
	weave_cross_axons(_mm(client))
	client.delete(collection_name=TARGET_COLLECTION, points_selector=models.PointIdsList(points=[work]))

	stats = weave_cross_axons(_mm(client))
	assert stats["axons_pruned"] >= 1
	assert _cross_axons(client, SOURCE_COLLECTION, social) == []


def test_soft_cap_deferred_prune(client, monkeypatch):
	monkeypatch.setattr(cfg, "AXON_MAX_CROSS", 3)
	social = _put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600)
	for _ in range(6):
		_put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 3600)

	weave_cross_axons(_mm(client))
	kept = _cross_axons(client, SOURCE_COLLECTION, social)
	assert len(kept) == 3  # pruned down to cap, heaviest kept


def test_local_associations_survive_weaving(client):
	social = _put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600, {"associations": ["legacy-local-id"]})
	_put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 7200)

	weave_cross_axons(_mm(client))
	payload = client.retrieve(collection_name=SOURCE_COLLECTION, ids=[social], with_payload=True)[0].payload
	assert "legacy-local-id" in payload["associations"]  # untouched, same wire format
	assert len(payload["associations"]) == 2


def test_structural_material_excluded(client):
	_put(client, SOURCE_COLLECTION, V_SIMILAR_A, NOW - 3600, {"lazarus_phase": "sequence_chunk"})
	_put(client, TARGET_COLLECTION, V_SIMILAR_B, NOW - 3600)
	stats = weave_cross_axons(_mm(client))
	assert stats["axons_woven"] == 0
