"""
Option A of the recall-visibility fix: every consolidated turn keeps a
searchable representative.

The hub is only synthesized when MORE than one chunk survives distillation
(consolidation.py: len(surviving_chunks) > 1), so single-survivor turns lived
only as sequence_chunk — structurally excluded from search. Live measurement
(2026-07-18): 1.553/2.359 work parents and 227/253 social parents had no hub;
~3.700 chunks invisible to direct recall.

Fix, two prongs:
1. Consolidation promotes the lone surviving chunk to synthesis_hub inline.
2. promote_orphan_chunks (sleep maintenance) is the self-healing/legacy pass:
   newest chunk of each hub-less parent gets promoted; multi-chunk parents are
   flagged hub_rebuild_pending for a future LLM re-synthesis.
"""


from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism.maintenance import promote_orphan_chunks

_LONE_CHUNK = "00000000-0000-0000-0000-0000000000b1"
_MULTI_1 = "00000000-0000-0000-0000-0000000000b2"
_MULTI_2 = "00000000-0000-0000-0000-0000000000b3"
_MULTI_3 = "00000000-0000-0000-0000-0000000000b4"
_HUBBED_CHUNK = "00000000-0000-0000-0000-0000000000b5"
_HUB = "00000000-0000-0000-0000-0000000000b6"


def _point(pid, phase, parent, created_at, content="engrama de prueba"):
	payload = {
		"content": content,
		"lazarus_phase": phase,
		"parent_id": parent,
		"created_at": created_at,
		"last_recalled_at": created_at,
		"reinforcement_score": 5.0,
		"immune": False,
		"color": "blue",
		"emotion": "neutral",
		"intensity": 0.5,
		"importance": 1.0,
	}
	return models.PointStruct(id=pid, vector=[0.1] * 384, payload=payload)


def _seed(mm: MemoryManager):
	mm._ensure_collection("work_memories")
	mm.client.upsert(
		collection_name="work_memories",
		points=[
			# Parent A: one lone chunk, no hub -> promote, no rebuild flag.
			_point(_LONE_CHUNK, "sequence_chunk", "parent-A", 100.0, "chunk solitario sin hub"),
			# Parent B: three chunks, no hub -> newest promoted + hub_rebuild_pending.
			_point(_MULTI_1, "sequence_chunk", "parent-B", 100.0),
			_point(_MULTI_2, "sequence_chunk", "parent-B", 200.0),
			_point(_MULTI_3, "sequence_chunk", "parent-B", 300.0),
			# Parent C: chunk + hub -> untouched.
			_point(_HUBBED_CHUNK, "sequence_chunk", "parent-C", 100.0),
			_point(_HUB, "synthesis_hub", "parent-C", 150.0),
		],
	)


def _payload(mm, pid):
	return mm.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=True)[0].payload


def test_lone_chunk_promoted_without_rebuild_flag(memory_manager):
	_seed(memory_manager)
	report = promote_orphan_chunks(memory_manager, collections=("work_memories",))

	assert report["work_memories"]["hubless_parents_promoted"] == 2  # parents A and B
	assert report["work_memories"]["multi_chunk_flagged"] == 1  # only B

	lone = _payload(memory_manager, _LONE_CHUNK)
	assert lone["lazarus_phase"] == "synthesis_hub"
	assert lone["promoted_from"] == "sequence_chunk"
	assert "hub_rebuild_pending" not in lone


def test_multichunk_parent_promotes_newest_and_flags_rebuild(memory_manager):
	_seed(memory_manager)
	promote_orphan_chunks(memory_manager, collections=("work_memories",))

	newest = _payload(memory_manager, _MULTI_3)
	assert newest["lazarus_phase"] == "synthesis_hub"
	assert newest["hub_rebuild_pending"] is True
	# Siblings stay as chunks
	assert _payload(memory_manager, _MULTI_1)["lazarus_phase"] == "sequence_chunk"
	assert _payload(memory_manager, _MULTI_2)["lazarus_phase"] == "sequence_chunk"


def test_hubbed_parent_untouched(memory_manager):
	_seed(memory_manager)
	promote_orphan_chunks(memory_manager, collections=("work_memories",))

	assert _payload(memory_manager, _HUBBED_CHUNK)["lazarus_phase"] == "sequence_chunk"
	assert _payload(memory_manager, _HUB)["lazarus_phase"] == "synthesis_hub"


def test_dry_run_reports_without_mutating(memory_manager):
	_seed(memory_manager)
	report = promote_orphan_chunks(memory_manager, collections=("work_memories",), dry_run=True)

	assert report["work_memories"]["hubless_parents_promoted"] == 2
	assert _payload(memory_manager, _LONE_CHUNK)["lazarus_phase"] == "sequence_chunk"
	assert _payload(memory_manager, _MULTI_3)["lazarus_phase"] == "sequence_chunk"


def test_promoted_chunk_becomes_searchable(memory_manager):
	"""End-to-end: before promotion the lone chunk is invisible to search;
	after promotion it comes back in results."""
	_seed(memory_manager)

	before = memory_manager.search_and_reinforce("work_memories", "chunk solitario", limit=10, deep_recall=True)
	assert all(str(r.id) != _LONE_CHUNK for r in before), "sequence_chunk must be excluded from search"

	promote_orphan_chunks(memory_manager, collections=("work_memories",))

	after = memory_manager.search_and_reinforce("work_memories", "chunk solitario", limit=10, deep_recall=True)
	assert any(str(r.id) == _LONE_CHUNK for r in after), "promoted chunk must be reachable by direct recall"
