"""
Hito 6: a read must not destroy data.

search_and_reinforce applied lazy decay and DELETED eroded engrams mid-lookup.
With READ_PATH_PRUNING_ENABLED=False (default) the eroded engram is hidden from
the result but stays in the collection; forgetting is the sleep cycle's job.
With the flag True, the legacy destructive behavior is restored.
"""

import time
from unittest.mock import patch

from qdrant_client.http import models

from red_pill.memory import MemoryManager

_ID = "00000000-0000-0000-0000-0000000000dd"


def _seed(mm: MemoryManager):
	mm._ensure_collection("work_memories")
	now = time.time()
	payload = {
		"content": "ENGRAM_TO_ERODE",
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
	mm.client.upsert(collection_name="work_memories", points=[models.PointStruct(id=_ID, vector=[0.1] * 384, payload=payload)])


def _count(mm: MemoryManager) -> int:
	return mm.client.count(collection_name="work_memories").count


class _ErodingEngine:
	def calculate_lazy_decay(self, payload, current_time):
		return {"_delete": True}


def test_read_does_not_delete_by_default(memory_manager, monkeypatch):
	_seed(memory_manager)
	monkeypatch.setattr(memory_manager.cfg, "READ_PATH_PRUNING_ENABLED", False, raising=False)
	with patch("red_pill.memory.get_memory_engine", return_value=_ErodingEngine()):
		results = memory_manager.search_and_reinforce("work_memories", "consulta", limit=10)

	assert all(str(r.id) != _ID for r in results), "eroded engram must be hidden from the result"
	assert _count(memory_manager) == 1, "but it must NOT be deleted from the collection"


def test_read_deletes_when_flag_enabled(memory_manager, monkeypatch):
	_seed(memory_manager)
	monkeypatch.setattr(memory_manager.cfg, "READ_PATH_PRUNING_ENABLED", True, raising=False)
	with patch("red_pill.memory.get_memory_engine", return_value=_ErodingEngine()):
		memory_manager.search_and_reinforce("work_memories", "consulta", limit=10)

	assert _count(memory_manager) == 0, "legacy destructive read: engram deleted"
