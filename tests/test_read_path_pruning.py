"""
Hito 6 (revised in the P0 recall fix): a read must not destroy data — nor hide it.

search_and_reinforce originally applied lazy decay and DELETED eroded engrams
mid-lookup; Hito 6 changed that to hiding them. Hiding turned out to be its own
P0: a hidden hit is never reinforced, so it can never rehabilitate (death spiral),
and with the Bayesian threshold bug 99% of work_memories vanished from recall.

Current contract with READ_PATH_PRUNING_ENABLED=False (default): the eroded
engram is RETURNED, flagged `_eroded=True`, demoted below healthy hits, and
reinforced like any other hit so real recalls rehabilitate it organically.
Forgetting is the sleep cycle's job. With the flag True, the legacy destructive
behavior is restored.
"""

import time
from unittest.mock import patch

from qdrant_client.http import models

from red_pill.memory import MemoryManager

_ID = "00000000-0000-0000-0000-0000000000dd"
_HEALTHY_ID = "00000000-0000-0000-0000-0000000000ee"


def _seed(mm: MemoryManager, immune: bool = False):
	mm._ensure_collection("work_memories")
	now = time.time()
	payload = {
		"content": "ENGRAM_TO_ERODE",
		"importance": 1.0,
		"reinforcement_score": 5.0,
		"created_at": now,
		"last_recalled_at": now,
		"immune": immune,
		"color": "gray",
		"emotion": "neutral",
		"intensity": 1.0,
		"lazarus_phase": "synthesis_hub",
	}
	mm.client.upsert(collection_name="work_memories", points=[models.PointStruct(id=_ID, vector=[0.1] * 384, payload=payload)])


def _seed_healthy(mm: MemoryManager):
	now = time.time()
	payload = {
		"content": "HEALTHY_ENGRAM",
		"importance": 1.0,
		"reinforcement_score": 5.0,
		"created_at": now,
		"last_recalled_at": now,
		"immune": False,
		"color": "gray",
		"emotion": "neutral",
		"intensity": 1.0,
		"lazarus_phase": "synthesis_hub",
	}
	mm.client.upsert(
		collection_name="work_memories", points=[models.PointStruct(id=_HEALTHY_ID, vector=[0.1] * 384, payload=payload)]
	)


def _count(mm: MemoryManager) -> int:
	return mm.client.count(collection_name="work_memories").count


class _ErodingEngine:
	"""Marks everything as eroded, reinforces nothing."""

	def calculate_lazy_decay(self, payload, current_time):
		return {"_delete": True}

	def calculate_reinforcement(self, payload, increment):
		return {"reinforcement_score": 5.0}


class _SelectiveErodingEngine(_ErodingEngine):
	"""Erodes only ENGRAM_TO_ERODE; the healthy engram survives."""

	def calculate_lazy_decay(self, payload, current_time):
		if payload.get("content") == "ENGRAM_TO_ERODE":
			return {"_delete": True}
		return {}


def test_read_returns_eroded_hit_demoted_by_default(memory_manager, monkeypatch):
	_seed(memory_manager)
	_seed_healthy(memory_manager)
	monkeypatch.setattr(memory_manager.cfg, "READ_PATH_PRUNING_ENABLED", False, raising=False)
	with patch("red_pill.memory.get_memory_engine", return_value=_SelectiveErodingEngine()):
		results = memory_manager.search_and_reinforce("work_memories", "consulta", limit=10)

	by_id = {str(r.id): r for r in results}
	assert _ID in by_id, "eroded engram must be returned, not hidden (hiding starves it of reinforcement)"
	assert by_id[_ID].payload.get("_eroded") is True, "eroded engram must be flagged for the caller"
	assert _HEALTHY_ID in by_id, "healthy engram must be returned"
	assert by_id[_HEALTHY_ID].payload.get("_eroded") is not True

	direct_ids = [str(r.id) for r in results if not (r.payload or {}).get("_is_evoked")]
	assert direct_ids.index(_HEALTHY_ID) < direct_ids.index(_ID), "healthy hits must outrank eroded ones"
	assert _count(memory_manager) == 2, "nothing may be deleted from the collection"


def test_eroded_hit_is_reinforced_for_rehabilitation(memory_manager, monkeypatch):
	"""A recalled eroded engram must re-enter the reinforcement loop (organic rehab)."""
	_seed(memory_manager)
	monkeypatch.setattr(memory_manager.cfg, "READ_PATH_PRUNING_ENABLED", False, raising=False)
	with patch("red_pill.memory.get_memory_engine", return_value=_ErodingEngine()):
		memory_manager.search_and_reinforce("work_memories", "consulta", limit=10)

	point = memory_manager.client.retrieve(collection_name="work_memories", ids=[_ID], with_payload=True)[0]
	assert point.payload.get("recall_count", 0) >= 1, "eroded hit must be reinforced on recall"


def test_immune_engram_never_marked_eroded(memory_manager, monkeypatch):
	_seed(memory_manager, immune=True)
	monkeypatch.setattr(memory_manager.cfg, "READ_PATH_PRUNING_ENABLED", False, raising=False)
	with patch("red_pill.memory.get_memory_engine", return_value=_ErodingEngine()):
		results = memory_manager.search_and_reinforce("work_memories", "consulta", limit=10)

	by_id = {str(r.id): r for r in results}
	assert _ID in by_id, "immune engram must always be returned"
	assert by_id[_ID].payload.get("_eroded") is not True, "immune engrams cannot erode"


def test_read_deletes_when_flag_enabled(memory_manager, monkeypatch):
	_seed(memory_manager)
	monkeypatch.setattr(memory_manager.cfg, "READ_PATH_PRUNING_ENABLED", True, raising=False)
	with patch("red_pill.memory.get_memory_engine", return_value=_ErodingEngine()):
		memory_manager.search_and_reinforce("work_memories", "consulta", limit=10)

	assert _count(memory_manager) == 0, "legacy destructive read: engram deleted"
