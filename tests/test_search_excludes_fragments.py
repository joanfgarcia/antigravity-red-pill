"""
Regression test for Hito 2: search_and_reinforce must hide raw material.

sequence_chunk (pre-synthesis chunks) and _is_fragment=True (oversized-engram
shrapnel) used to be returned by semantic search, burying the distilled hubs.
Only raw_parent was excluded before. Here we insert three engrams into an
in-memory Qdrant and assert the search returns the distilled hub only.

Uses the in-memory MemoryManager (conftest forces :memory: + a fastembed stub
that returns a constant vector, so the filter — not similarity — decides.)
"""

import time

from qdrant_client.http import models

from red_pill.memory import MemoryManager

_NORMAL_ID = "00000000-0000-0000-0000-0000000000aa"
_CHUNK_ID = "00000000-0000-0000-0000-0000000000bb"
_FRAG_ID = "00000000-0000-0000-0000-0000000000cc"


def _payload(content: str, **extra):
	now = time.time()
	base = {
		"content": content,
		"importance": 5.0,
		"reinforcement_score": 5.0,
		"created_at": now,
		"last_recalled_at": now,
		"immune": True,  # keep the normal engram safe from decay during the read
		"color": "gray",
		"emotion": "neutral",
		"intensity": 1.0,
		"utility_alpha": 10.0,
		"utility_beta": 1.0,
	}
	base.update(extra)
	return base


def _seed(mm: MemoryManager):
	mm._ensure_collection("work_memories")
	vector = [0.1] * 384
	points = [
		models.PointStruct(id=_NORMAL_ID, vector=vector, payload=_payload("DISTILLED_HUB", lazarus_phase="synthesis_hub")),
		models.PointStruct(id=_CHUNK_ID, vector=vector, payload=_payload("RAW_CHUNK", lazarus_phase="sequence_chunk")),
		models.PointStruct(id=_FRAG_ID, vector=vector, payload=_payload("SHRAPNEL", _is_fragment=True)),
	]
	mm.client.upsert(collection_name="work_memories", points=points)


def test_search_excludes_chunks_and_fragments(memory_manager):
	_seed(memory_manager)
	results = memory_manager.search_and_reinforce("work_memories", "cualquier consulta", limit=10)
	ids = {str(r.id) for r in results}

	assert _NORMAL_ID in ids, "the distilled hub must be retrievable"
	assert _CHUNK_ID not in ids, "sequence_chunk must be excluded"
	assert _FRAG_ID not in ids, "_is_fragment must be excluded"


def test_deep_recall_also_excludes_raw_material(memory_manager):
	_seed(memory_manager)
	# deep_recall drops the score filter but must keep the structural exclusions
	results = memory_manager.search_and_reinforce("work_memories", "cualquier consulta", limit=10, deep_recall=True)
	ids = {str(r.id) for r in results}

	assert _NORMAL_ID in ids
	assert _CHUNK_ID not in ids
	assert _FRAG_ID not in ids
