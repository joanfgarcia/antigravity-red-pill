"""HygienePhase: empty-engram purge with raw-chain restitching."""

import time
import uuid

import pytest
from qdrant_client import models

import red_pill.config as cfg
from red_pill.metabolism.maintenance import purge_empty_engrams

DIM = cfg.VECTOR_SIZE
NOW = time.time()


def _put(mm, collection, content, **extra):
	pid = str(uuid.uuid4())
	payload = {"content": content, "created_at": NOW, **extra}
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


def _get(mm, col, pid):
	records = mm.client.retrieve(collection_name=col, ids=[pid], with_payload=True)
	return records[0].payload if records else None


def test_purges_empty_and_restitches_chain(mm):
	a = _put(mm, "work_memories", "contenido real A", lazarus_phase="raw_parent")
	b = _put(mm, "work_memories", "   ", lazarus_phase="raw_parent")  # vacío (whitespace)
	c = _put(mm, "work_memories", "contenido real C", lazarus_phase="raw_parent")
	mm.client.set_payload(collection_name="work_memories", payload={"next_raw_parent": b}, points=[a])
	mm.client.set_payload(collection_name="work_memories", payload={"prev_raw_parent": a, "next_raw_parent": c}, points=[b])
	mm.client.set_payload(collection_name="work_memories", payload={"prev_raw_parent": b}, points=[c])

	report = purge_empty_engrams(mm)
	assert report["work_memories"]["empty_purged"] == 1
	assert _get(mm, "work_memories", b) is None
	assert _get(mm, "work_memories", a)["next_raw_parent"] == c  # A -> C
	assert _get(mm, "work_memories", c)["prev_raw_parent"] == a  # C -> A


def test_chain_end_keys_removed_not_dangled(mm):
	a = _put(mm, "work_memories", "real", lazarus_phase="raw_parent")
	b = _put(mm, "work_memories", "", lazarus_phase="raw_parent")  # vacío al final de cadena
	mm.client.set_payload(collection_name="work_memories", payload={"next_raw_parent": b}, points=[a])
	mm.client.set_payload(collection_name="work_memories", payload={"prev_raw_parent": a}, points=[b])

	purge_empty_engrams(mm)
	payload_a = _get(mm, "work_memories", a)
	assert "next_raw_parent" not in payload_a  # el extremo se limpia, no apunta al vacío borrado


def test_immune_empty_skipped_and_reported(mm):
	pid = _put(mm, "work_memories", "", immune=True)
	report = purge_empty_engrams(mm)
	assert report["work_memories"]["skipped_immune_empty"] == 1
	assert _get(mm, "work_memories", pid) is not None


def test_non_empty_untouched_and_dry_run(mm):
	real = _put(mm, "work_memories", "contenido")
	empty = _put(mm, "work_memories", "")
	report = purge_empty_engrams(mm, dry_run=True)
	assert report["work_memories"]["empty_purged"] == 1  # contado
	assert _get(mm, "work_memories", empty) is not None  # pero no borrado
	assert _get(mm, "work_memories", real) is not None
