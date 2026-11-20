"""RFC-OLV-001 · F0 — el contador de recuperaciones no miente.

La escalera entera cuelga de `recall_count` / `recall_stamps`: si el contador no
se incrementa en una recuperación real, el sumidero purgaría memoria usada y
«olvidar bien» sería una lotería. Este test es el candado de D-12 y es
bloqueante: si falla, la escalera se queda apagada.

Alcance de la medida (D-18):
- SÍ cuenta: cualquier camino que pase por `search_and_reinforce`.
- NO cuenta: inmunes (`memory.py:435`) ni las lecturas de síntesis (diseño
  explícito, `synthesis_common.py`).
"""

from red_pill.memory import MemoryManager

_TEXT = "la niebla sobre el puerto de BCN a las cinco de la mañana"


def test_recall_increments_counter_and_timestamp(memory_manager: MemoryManager):
	memory_manager._ensure_collection("work_memories")
	memory_manager.add_memory(
		collection="work_memories",
		text=_TEXT,
		metadata={"origin": "f0_probe"},
		emotion="neutral",
		intensity=0.5,
	)
	points = memory_manager.client.scroll(collection_name="work_memories", limit=10, with_payload=True)[0]
	assert len(points) == 1
	pid = points[0].id
	before = points[0].payload or {}
	assert int(before.get("recall_count") or 0) == 0
	assert before.get("last_recalled_at")

	hits = memory_manager.search_and_reinforce("work_memories", _TEXT, limit=1, caller="f0")
	assert hits, "la recuperación no devolvió nada: el test no mide nada"

	after = memory_manager.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=True)[0].payload or {}
	assert int(after.get("recall_count") or 0) == 1, "F0: una recuperación real DEBE incrementar recall_count"
	assert float(after["last_recalled_at"]) >= float(before["last_recalled_at"])


def test_immune_points_do_not_count(memory_manager: MemoryManager):
	"""D-18: los inmunes quedan fuera de todo reloj, también del contador."""
	memory_manager._ensure_collection("directive_memories")
	memory_manager.add_memory(
		collection="directive_memories",
		text=_TEXT,
		metadata={"origin": "f0_probe", "immune": True},
		emotion="neutral",
		intensity=0.5,
	)
	points = memory_manager.client.scroll(collection_name="directive_memories", limit=10, with_payload=True)[0]
	pid = points[0].id
	memory_manager.client.set_payload(collection_name="directive_memories", payload={"immune": True}, points=[pid])
	memory_manager.search_and_reinforce("directive_memories", _TEXT, limit=1, caller="f0")
	after = memory_manager.client.retrieve(collection_name="directive_memories", ids=[pid], with_payload=True)[0].payload or {}
	assert int(after.get("recall_count") or 0) == 0, "un inmune no se refuerza ni cuenta"
