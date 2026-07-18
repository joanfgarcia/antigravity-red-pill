"""R2: RevisionPhase — dry-run marks, execute moves leafs (same ID), hubs locked."""

import time
import uuid

import pytest
from qdrant_client import models

import red_pill.config as cfg
from red_pill.metabolism.revision import REVIEWED_KEY, WOULD_MOVE_KEY, backlog_count, revise_classifications

DIM = cfg.VECTOR_SIZE
NOW = time.time()


def _put(mm, collection, content, **extra):
	pid = str(uuid.uuid4())
	payload = {"content": content, "created_at": NOW, "importance": 1.0, "reinforcement_score": 1.0, **extra}
	vec = [1.0] + [0.0] * (DIM - 1)
	mm.client.upsert(collection_name=collection, points=[models.PointStruct(id=pid, vector=vec, payload=payload)])
	return pid


@pytest.fixture()
def mm(memory_manager):
	existing = {c.name for c in memory_manager.client.get_collections().collections}
	for col in ("work_memories", "social_memories"):
		if col not in existing:
			memory_manager.client.create_collection(collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
	return memory_manager


@pytest.fixture()
def social_classifier(monkeypatch):
	"""Every engram is 'really' social — simulates the R1-era misrouting."""
	import red_pill.metabolism.revision as revision_module

	monkeypatch.setattr(revision_module, "classify_category", lambda text: "social")


def _get(mm, collection, pid):
	records = mm.client.retrieve(collection_name=collection, ids=[pid], with_payload=True)
	return records[0].payload if records else None


def test_dry_run_marks_without_moving(mm, social_classifier):
	pid = _put(mm, "work_memories", "charla personal mal archivada")
	stats = revise_classifications(mm, batch_size=10, dry_run=True)
	assert stats["would_move"] == 1 and stats["moved"] == 0
	payload = _get(mm, "work_memories", pid)
	assert payload is not None  # still in place
	assert payload[WOULD_MOVE_KEY] == "social_memories"
	assert payload[REVIEWED_KEY] > 0


def test_execute_moves_leaf_same_id(mm, social_classifier):
	pid = _put(mm, "work_memories", "charla personal mal archivada")
	stats = revise_classifications(mm, batch_size=10, dry_run=False)
	assert stats["moved"] == 1
	assert _get(mm, "work_memories", pid) is None
	moved = _get(mm, "social_memories", pid)
	assert moved is not None and moved["category"] == "social"


def test_execute_rewires_reciprocal_axon(mm, social_classifier):
	twin = _put(mm, "social_memories", "recuerdo social", **{REVIEWED_KEY: NOW})
	pid = _put(
		mm, "work_memories", "charla mal archivada",
		associations=[{"id": twin, "target_collection": "social_memories", "weight": 0.8, "association_type": "temporal_semantic"}],
	)
	mm.client.set_payload(
		collection_name="social_memories",
		payload={"associations": [{"id": pid, "target_collection": "work_memories", "weight": 0.8, "association_type": "temporal_semantic"}]},
		points=[twin],
	)
	stats = revise_classifications(mm, batch_size=10, dry_run=False)
	assert stats["moved"] == 1 and stats["axons_rewired"] == 1
	twin_payload = _get(mm, "social_memories", twin)
	assert twin_payload["associations"][0]["target_collection"] == "social_memories"  # rewired to follow the move


def test_hub_never_moved(mm, social_classifier):
	pid = _put(mm, "work_memories", "hub mal clasificado", lazarus_phase="synthesis_hub")
	stats = revise_classifications(mm, batch_size=10, dry_run=False)
	assert stats["hubs_flagged"] == 1 and stats["moved"] == 0
	payload = _get(mm, "work_memories", pid)
	assert payload is not None and payload.get("hub_locked") is True


def test_immune_untouched(mm, social_classifier):
	pid = _put(mm, "work_memories", "directiva soberana", immune=True)
	stats = revise_classifications(mm, batch_size=10, dry_run=False)
	assert stats["reviewed"] == 0
	payload = _get(mm, "work_memories", pid)
	assert REVIEWED_KEY not in payload


def test_confirmed_category_just_marked(mm, monkeypatch):
	import red_pill.metabolism.revision as revision_module

	monkeypatch.setattr(revision_module, "classify_category", lambda text: "work")
	pid = _put(mm, "work_memories", "de verdad es trabajo")
	stats = revise_classifications(mm, batch_size=10, dry_run=False)
	assert stats["confirmed"] == 1 and stats["moved"] == 0
	assert _get(mm, "work_memories", pid)[REVIEWED_KEY] > 0


def test_llm_failure_leaves_unmarked_for_retry(mm, monkeypatch):
	import red_pill.metabolism.revision as revision_module

	monkeypatch.setattr(revision_module, "classify_category", lambda text: None)
	pid = _put(mm, "work_memories", "algo")
	stats = revise_classifications(mm, batch_size=10, dry_run=False)
	assert stats["llm_failures"] == 1
	assert REVIEWED_KEY not in _get(mm, "work_memories", pid)


def test_batch_size_respected_and_backlog_counts(mm, social_classifier):
	for i in range(5):
		_put(mm, "work_memories", f"engrama {i}")
	stats = revise_classifications(mm, batch_size=3, dry_run=True)
	assert stats["reviewed"] == 3
	counts = backlog_count(mm.client)
	assert counts["work_memories"] == 2
