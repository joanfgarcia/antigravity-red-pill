"""
Hito 9: search_and_reinforce must emit a RecallEvent (memory-utility metric).
First measurement of whether recalled memory is actually useful.
"""

import time

from qdrant_client.http import models

from red_pill.events import RecallEvent, get_event_bus

_ID = "00000000-0000-0000-0000-0000000000ee"


def _seed(mm):
	mm._ensure_collection("work_memories")
	now = time.time()
	mm.client.upsert(
		collection_name="work_memories",
		points=[
			models.PointStruct(
				id=_ID,
				vector=[0.1] * 384,
				payload={
					"content": "engrama recuperable",
					"importance": 5.0,
					"reinforcement_score": 5.0,
					"created_at": now,
					"last_recalled_at": now,
					"immune": True,
					"color": "gray",
					"lazarus_phase": "synthesis_hub",
					"emotion": "neutral",
					"intensity": 1.0,
					"utility_alpha": 10.0,
					"utility_beta": 1.0,
				},
			)
		],
	)


def test_search_emits_recall_event(memory_manager):
	_seed(memory_manager)
	captured = []
	bus = get_event_bus()

	def _listener(ev):
		captured.append(ev)

	bus.subscribe(RecallEvent, _listener)
	try:
		memory_manager.search_and_reinforce("work_memories", "consulta de prueba", limit=5, caller="test_caller")
	finally:
		bus.unsubscribe(RecallEvent, _listener)

	assert len(captured) == 1
	ev = captured[0]
	assert ev.caller == "test_caller"
	assert ev.collection == "work_memories"
	assert ev.query_len == len("consulta de prueba")
	assert ev.hits >= 1
	assert ev.top_score is not None
