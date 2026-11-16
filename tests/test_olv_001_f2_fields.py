"""RFC-OLV-001 · F2 — un campo, un significado.

- `last_recalled_at`: SOLO lo escriben el nacimiento y la recuperación. Si el
  erosor lo firmara, la «edad» sería un metrónomo y el uso, invisible (D-09).
- `decay_checked_at`: SOLO lo escribe la pasada de olvido (cursor de la
  consulta indexada, que es la eficiencia que se buscaba en abril).
- `recall_stamps`: historia de las últimas recuperaciones (ring de 5), para la
  puerta de espaciado de D-06.
"""

import time

from qdrant_client.http import models

from red_pill.memory import MemoryManager
from red_pill.metabolism.maintenance import erode_work_hubs

_HUB = "00000000-0000-0000-0000-00000000cc01"
_TEXT = "el río Besòs a su paso por Santa Coloma, con la niebla baja"

DAY = 86400.0


def _leafless_stale_hub(now: float) -> models.PointStruct:
	return models.PointStruct(
		id=_HUB,
		vector=[0.1] * 384,
		payload={
			"content": "rama seca",
			"lazarus_phase": "synthesis_hub",
			"utility_alpha": 1.0,
			"utility_beta": 1.0,
			"reinforcement_score": 0.5,
			"intensity": 0.5,
			"immune": False,
			"created_at": now - DAY,
			"last_recalled_at": now - DAY,
		},
	)


def test_decay_pass_does_not_touch_last_recalled_at(memory_manager: MemoryManager):
	"""C-04: un ciclo sin recuperaciones no cambia el campo de uso; sí el del erosor."""
	memory_manager._ensure_collection("work_memories")
	now = time.time()
	memory_manager.client.upsert(collection_name="work_memories", points=[_leafless_stale_hub(now)])

	before = memory_manager.client.retrieve(collection_name="work_memories", ids=[_HUB], with_payload=True)[0].payload or {}
	erode_work_hubs(memory_manager)
	after = memory_manager.client.retrieve(collection_name="work_memories", ids=[_HUB], with_payload=True)[0].payload or {}

	assert after["last_recalled_at"] == before["last_recalled_at"], "el erosor no puede firmar el campo de uso"
	assert after["decay_checked_at"] >= before["last_recalled_at"], "el cursor del erosor sí avanza"
	assert after["utility_beta"] > before["utility_beta"], "y el decaimiento ocurrió de verdad"


def test_recall_history_is_a_ring_of_five(memory_manager: MemoryManager):
	"""D-06/F2: se guardan las últimas 5 recuperaciones, con su instante."""
	memory_manager._ensure_collection("work_memories")
	memory_manager.add_memory(
		collection="work_memories",
		text=_TEXT,
		metadata={"origin": "f2_probe"},
		emotion="neutral",
		intensity=0.5,
	)
	pid = memory_manager.client.scroll(collection_name="work_memories", limit=1, with_payload=True)[0][0].id

	for _ in range(7):
		memory_manager.search_and_reinforce("work_memories", _TEXT, limit=1, caller="f2")

	payload = memory_manager.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=True)[0].payload or {}
	stamps = payload.get("recall_stamps") or []
	assert len(stamps) == 5, f"el ring debe quedarse en 5, tiene {len(stamps)}"
	assert stamps == sorted(stamps), "las marcas van en orden cronológico"
	assert int(payload.get("recall_count") or 0) == 7, "el contador acumulado no se recorta"
