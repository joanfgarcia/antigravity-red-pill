"""Dos engramas por turno: el del Operador y el del agente (2026-11-20).

Un turno no tiene un ánimo: tiene dos. El del Operador sale de lo que escribe él
y el del agente de lo que responde; con un solo punto por par, el etiquetador
tenía que inventar una media de dos voces y el ánimo del Operador quedaba
contaminado por su propio agente.

El contrato que fija este test:
- dos puntos, uno por lado, con `metadata.author` explícito;
- el texto de cada lado es SU texto (nada de pares "USER: … ASSISTANT: …");
- un lado vacío no escribe punto (no se guardan engramas fantasma).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from red_pill.memory import MemoryManager


def _manager() -> MemoryManager:
	m = MemoryManager.__new__(MemoryManager)
	m.client = MagicMock()
	m._get_vector = MagicMock(return_value=[0.0] * 384)
	m._ensure_collection = MagicMock()
	return m


def test_escribe_dos_engramas_con_autor():
	m = _manager()
	op, ag = m.record_interaction_turn("¿qué tal el día?", "Bien, con trabajo.", originator="opencode")

	pts = m.client.upsert.call_args.kwargs["points"]
	assert len(pts) == 2
	assert op and ag and op != ag
	autores = {p.payload["metadata"]["author"] for p in pts}
	assert autores == {"operator", "agent"}

	contenidos = [p.payload["content"] for p in pts]
	assert any("¿qué tal el día?" in c and "Bien, con trabajo." not in c for c in contenidos)
	assert any("Bien, con trabajo." in c and "¿qué tal el día?" not in c for c in contenidos)


def test_un_lado_vacio_no_escribe_punto():
	m = _manager()
	op, ag = m.record_interaction_turn("solo pregunto", "", originator="opencode")
	pts = m.client.upsert.call_args.kwargs["points"]
	assert len(pts) == 1
	assert pts[0].payload["metadata"]["author"] == "operator"
	assert ag == ""


def test_procedencia_y_sesion_llegan_a_los_dos():
	m = _manager()
	m.record_interaction_turn("p", "r", originator="opencode", model="m", session_id="ses_x")
	for p in m.client.upsert.call_args.kwargs["points"]:
		assert p.payload["metadata"]["originator"] == "opencode"
		assert p.payload["metadata"]["session_id"] == "ses_x"
