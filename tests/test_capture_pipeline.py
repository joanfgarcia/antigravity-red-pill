"""Captura de turnos: una sola tubería, del hook al engrama.

Durante un mes hubo dos sumideros: cuatro superficies de captura escribían en
una tabla `interactions` que nadie leía, mientras la memoria se alimentaba solo
de la vía que el modelo debía recordar invocar. Estas pruebas fijan la tubería
única — capturar → `memory_queue` → `interaction_memories` — y las tres
propiedades que la hacen fiable: deduplicación en el sumidero (no depende del
modelo), procedencia hasta Qdrant, y limpieza de ruido en un único punto.
"""

from unittest.mock import MagicMock, patch

import pytest

from red_pill.core.queue_manager import MemoryQueueManager


@pytest.fixture
def queue(tmp_path):
	return MemoryQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


# ── Deduplicación en el sumidero ───────────────────────────────────────────


def test_same_turn_from_two_producers_lands_once(queue):
	"""El hook del editor y el relay del agente pueden ver el MISMO turno.

	La corrección no puede depender de que el modelo se porte bien, así que el
	guard vive aquí y no en las anclas.
	"""
	first = queue.enqueue_memory("¿cómo va el entrenamiento?", "por la época 998", "assistant", originator="claude_code")
	second = queue.enqueue_memory("¿cómo va el entrenamiento?", "por la época 998", "assistant", originator="handshake_relay")

	assert second == first  # devuelve la fila existente, no crea otra
	assert len(queue.dequeue_pending(limit=10)) == 1


def test_different_turns_are_not_confused(queue):
	queue.enqueue_memory("pregunta A", "respuesta A", "assistant")
	queue.enqueue_memory("pregunta B", "respuesta B", "assistant")

	assert len(queue.dequeue_pending(limit=10)) == 2


def test_repeating_a_turn_much_later_is_allowed(queue):
	"""Preguntar dos veces lo mismo en días distintos son dos recuerdos."""
	import sqlite3

	queue.enqueue_memory("¿qué tal?", "bien", "assistant")
	with sqlite3.connect(queue.db_path) as conn:  # envejecemos la fila un día
		conn.execute("UPDATE memory_queue SET created_at = created_at - 86400")

	queue.enqueue_memory("¿qué tal?", "bien", "assistant", dedup_window_hours=12)

	assert len(queue.dequeue_pending(limit=10)) == 2


def test_backfill_dedups_against_the_whole_history(queue):
	"""Rescatar turnos viejos dos veces no puede duplicarlos."""
	import sqlite3

	queue.enqueue_memory("turno histórico", "respuesta", "assistant", dedup_window_hours=None)
	with sqlite3.connect(queue.db_path) as conn:
		conn.execute("UPDATE memory_queue SET created_at = created_at - 86400 * 40")

	queue.enqueue_memory("turno histórico", "respuesta", "assistant", dedup_window_hours=None)

	assert len(queue.dequeue_pending(limit=10)) == 1


def test_dedup_can_be_disabled(queue):
	queue.enqueue_memory("otra vez", "sí", "assistant", dedup_window_hours=0)
	queue.enqueue_memory("otra vez", "sí", "assistant", dedup_window_hours=0)

	assert len(queue.dequeue_pending(limit=10)) == 2


# ── Procedencia: de qué IDE viene cada engrama ─────────────────────────────


def test_originator_survives_the_queue(queue):
	queue.enqueue_memory("hola", "qué tal", "assistant", originator="opencode", model="big-pickle")

	item = queue.dequeue_pending(limit=1)[0]

	assert item["originator"] == "opencode"
	assert item["model"] == "big-pickle"


def test_originator_reaches_the_engram():
	"""Antes moría al ingerir: la cola lo llevaba y `record_interaction_pair` no lo aceptaba."""
	from red_pill.memory import MemoryManager

	manager = MemoryManager.__new__(MemoryManager)
	manager.client = MagicMock()
	manager._get_vector = MagicMock(return_value=[0.0] * 384)
	manager._ensure_collection = MagicMock()

	manager.record_interaction_pair("p", "r", model="claude-fable-5", originator="claude_code")

	point = manager.client.upsert.call_args.kwargs["points"][0]
	assert point.payload["metadata"]["originator"] == "claude_code"
	assert point.payload["metadata"]["model"] == "claude-fable-5"


# ── Limpieza de ruido en un único punto ────────────────────────────────────


def test_noise_filter_runs_at_the_drain_not_at_each_capture():
	"""Los capturadores son tontos a propósito (el plugin JS ni siquiera puede
	llamar a Python); limpiar al drenar mantiene a todos idénticos."""
	from red_pill.core.queue_worker import _clean_turn

	prompt, response = _clean_turn("una pregunta con sustancia suficiente", "una respuesta con sustancia suficiente")

	assert prompt and response


def test_turn_that_is_only_tooling_noise_is_dropped():
	from red_pill.core.queue_worker import _clean_turn

	assert _clean_turn("ok", "ok") == ("", "")


def test_filter_failure_never_loses_the_turn():
	"""Si el filtro revienta, se ingiere crudo: perder el turno sería peor."""
	from red_pill.core import queue_worker

	with patch("red_pill.utils.telemetry_filter.filter_noise_from_turn", side_effect=RuntimeError("boom")):
		assert queue_worker._clean_turn("prompt largo de verdad", "respuesta larga de verdad") == (
			"prompt largo de verdad",
			"respuesta larga de verdad",
		)


# ── El sumidero es único ───────────────────────────────────────────────────


def test_bridges_queue_instead_of_writing_their_own_table(tmp_path, monkeypatch):
	"""El bridge headless (Telegram/agy) no tiene hook que le capture el turno,
	así que captura él — pero a la cola de todos, no a una tabla propia."""
	from red_pill.swarm.bridges.opencode import OpenCodeBridge

	captured = {}
	monkeypatch.setattr(
		"red_pill.core.queue_manager.MemoryQueueManager.enqueue_memory",
		lambda self, **kw: captured.update(kw) or 1,
	)

	bridge = OpenCodeBridge.__new__(OpenCodeBridge)
	bridge._scribe_relay("pregunta", "respuesta", model="big-pickle")

	assert captured["originator"] == "opencode"
	assert captured["prompt"] == "pregunta"
	assert captured["response"] == "respuesta"


def test_the_dead_end_archiver_is_gone():
	"""El plugin del Janitor barría a un JSONL turnos que nunca fueron memoria."""
	from red_pill.swarm.agents.janitor import discover_plugins

	assert "sqlite_interactions_archiver" not in {p.name for p in discover_plugins()}
