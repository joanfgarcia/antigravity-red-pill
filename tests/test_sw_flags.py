"""Gating de los feature flags del single-writer (CONVENTIONS RULE 4).

Verifica que cada interruptor realmente gobierna su componente: OFF = nada cambia,
ON = comportamiento nuevo. Sin esto, un flag mal cableado pasaría desapercibido.
"""

from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.core.queue_worker import drain_memory_queue


class FakeMemory:
	def __init__(self):
		self.calls: list[dict] = []

	def record_interaction_pair(self, **kwargs):
		self.calls.append(kwargs)
		return "id"


def _queue(tmp_path):
	q = MemoryQueueManager(db_path=str(tmp_path / "q.db"))
	q.enqueue_memory(
		"¿Cómo va el entrenamiento de BitNet?",
		"Por la época 998, sin incidencias reseñables.",
		"assistant",
		originator="opencode",
		session_id="ses_x",
		affinity=["ws:sharing", "mission:BIT"],
	)
	return q


def test_flags_sw_default_off():
	import red_pill.config as cfgmod

	assert cfgmod.SW_AFFINITY_ENABLED is False
	assert cfgmod.SW_PURGE_GATE_ENABLED is False
	assert cfgmod.SW_DEDUP_ENABLED is False


def test_affinity_off_no_pasa_sesion_al_engrama(tmp_path, monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_AFFINITY_ENABLED", False, raising=False)
	mem = FakeMemory()
	drain_memory_queue(_queue(tmp_path), mem, limit=10)
	assert mem.calls and "session_id" not in mem.calls[0] and "affinity" not in mem.calls[0]


def test_affinity_on_pasa_sesion_y_afinidad(tmp_path, monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_AFFINITY_ENABLED", True, raising=False)
	mem = FakeMemory()
	drain_memory_queue(_queue(tmp_path), mem, limit=10)
	assert mem.calls[0]["session_id"] == "ses_x"
	assert mem.calls[0]["affinity"] == ["ws:sharing", "mission:BIT"]
