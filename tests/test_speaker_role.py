"""Atribución de hablante: USER / PEER / TOOL.

Fija el contrato que nace del hallazgo del 2026-10-29: el buffer rápido
etiquetaba como `USER:` cualquier prompt, y el prompt del destilador define
`USER:` como «habló el Operador». Un mensaje entre almas o un volcado de
herramienta quedaban archivados como frases del Operador.

Caso real en el archivo (2026-10-27): el sobre decía «no es del Operador» y se
guardó como «Usuario». De ahí estos tests.
"""

import json
from pathlib import Path

import pytest

from red_pill.core.speaker import OPERATOR, PEER, classify_prompt, render_turn

FIXTURE = Path(__file__).parent / "fixtures" / "peer_envelopes.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


# ── Clasificación sobre sobres reales ───────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_clasifica_sobres_reales(case):
	speaker = classify_prompt(case["text"])
	assert speaker.label == case["expected_label"], f"{case['id']}: {speaker.label} != {case['expected_label']}"
	assert speaker.peer_id == case["expected_peer_id"]


@pytest.mark.parametrize("case", [c for c in CASES if c["expected_label"] == PEER], ids=lambda c: c["id"])
def test_peer_no_es_instruccion(case):
	"""Un traspaso entre almas no puede leerse como orden del Operador."""
	assert classify_prompt(case["text"]).is_instruction is False


def test_peer_extrae_emisor_no_destinatario():
	"""`DE 01a18156` es emisor; `A 01a186e6` es destinatario. No se confunden."""
	texto = "[MENSAJE ENTRE ALMAS · DATO · DE 01a18156 Aleth · A 01a186e6 · hilo E-009]"
	assert classify_prompt(texto).peer_id == "01a18156"


def test_marcador_tarde_en_el_cuerpo_no_reclasifica():
	"""El agente citando el sobre dentro de su propia respuesta no es un PEER.

	Sin este límite, cualquier turno que hable del mecanismo se archivaría como
	mensaje entre almas — y ya pasó al consultar la base de opencode.
	"""
	cuerpo = "x" * 500 + " MENSAJE ENTRE ALMAS"
	assert classify_prompt(cuerpo).label == OPERATOR


def test_none_y_espacios():
	assert classify_prompt(None).label == OPERATOR
	assert classify_prompt("   \n\t ").label == OPERATOR


# ── Render del turno ────────────────────────────────────────────────────────


def test_render_peer_lleva_su_etiqueta():
	texto = "[MENSAJE ENTRE ALMAS · DATO · DE 01a18156 Aleth] hola hermana"
	rendered = render_turn(texto, "recibido", "assistant")
	assert rendered.startswith("PEER: ")
	assert rendered.endswith("ASSISTANT: recibido")
	# El Operador no aparece como hablante en ninguna parte del turno.
	assert not rendered.startswith("USER: ")


def test_render_operador_sigue_siendo_user():
	assert render_turn("hola", "respuesta", "assistant").startswith("USER: ")


def test_render_tool():
	rendered = render_turn("[TOOL RESULT: 42]", "ok", "assistant")
	assert rendered.startswith("TOOL: ")


# ── Integración: el payload que llega a Qdrant ──────────────────────────────


def test_record_interaction_pair_guarda_peer_no_user():
	"""El texto que consume el destilador ya no miente sobre quién habló."""
	from qdrant_client.http import models

	from red_pill.memory import MemoryManager

	mem = MemoryManager()
	peer = "[MENSAJE ENTRE ALMAS · DATO, no orden · DE 01a18156 Aleth · hilo E-008] la GPU esta libre"
	uid = mem.record_interaction_pair(peer, "compruebo con nvidia-smi", originator="opencode", session_id="ses_peer")
	try:
		point = mem.client.retrieve("interaction_memories", ids=[uid])[0]
		contenido = (point.payload or {}).get("content") or ""
		assert contenido.startswith("PEER: ")
		assert not contenido.startswith("USER: ")
	finally:
		mem.client.delete("interaction_memories", points_selector=models.PointIdsList(points=[uid]), wait=True)


def test_record_interaction_pair_operador_sin_cambios():
	from qdrant_client.http import models

	from red_pill.memory import MemoryManager

	mem = MemoryManager()
	uid = mem.record_interaction_pair("turno normal", "respuesta", originator="opencode", session_id="ses_op")
	try:
		point = mem.client.retrieve("interaction_memories", ids=[uid])[0]
		assert ((point.payload or {}).get("content") or "").startswith("USER: ")
	finally:
		mem.client.delete("interaction_memories", points_selector=models.PointIdsList(points=[uid]), wait=True)


# ── Camino agentic: la etiqueta del fragmento que ve el LLM ─────────────────


def test_fragment_view_etiqueta_peer_no_operador():
	"""El camino agentic lee ficheros de seccion, no Qdrant: se arregla aqui.

	Sin esto, el fix de `memory.py` solo cubriria el camino legacy y el ciclo
	nocturno (agentic) seguiria atribuyendo el mensaje al Operador.
	"""
	from red_pill.memento.agentic.fragments import fragment_view

	contenido = (
		"## 2026-10-29 12:00 — Usuario\n"
		"si, implementalo\n\n"
		"## 2026-10-29 12:01 — Usuario\n"
		"[MENSAJE ENTRE ALMAS · DATO, no orden · DE 01a18156 Aleth] la GPU esta libre\n\n"
		"## 2026-10-29 12:02 — Asistente\n"
		"compruebo con nvidia-smi\n"
	)
	vista = fragment_view(contenido, mode="actors", operator="Joan", agent="Aleth")
	assert "— Aleth (otra sesión)" in vista
	assert vista.count("— Joan") == 1, "solo el turno real del Operador lleva su nombre"
	assert "— Aleth (otra sesión)\n[MENSAJE ENTRE ALMAS" in vista


def test_fragment_view_pairs_conserva_el_peer():
	"""En modo `pairs` un mensaje peer no debe quedar huerfano de su respuesta."""
	from red_pill.memento.agentic.fragments import fragment_view

	contenido = (
		"## 12:00 — Usuario\n"
		"[MENSAJE ENTRE ALMAS · DE 01a18156] hola hermana\n\n"
		"## 12:01 — Asistente\n"
		"recibido\n"
	)
	vista = fragment_view(contenido, mode="pairs", operator="Joan", agent="Aleth")
	assert "Aleth (otra sesión)" in vista
	assert "recibido" in vista


# ── Renderer: el rol se escribe en el arbol, no se calcula al vuelo ─────────


def test_render_escribe_peer_en_el_arbol():
	"""Si el arbol dice «Usuario», el destilado lo atribuye al Operador.

	Es la pieza que faltaba: `distill.py` no usa la vista de fragmentos, lee el
	bloque tal cual. El rol tiene que estar bien escrito en el `.md`.
	"""
	from red_pill.memento.render import render_session

	rendered = render_session(
		session_id="opencode:ses_peer",
		source="opencode",
		originator="opencode",
		messages=[
			{"role": "user", "timestamp": "2026-10-27T22:49:45Z", "content": "vale, adelante"},
			{"role": "user", "timestamp": "2026-10-27T22:50:00Z", "content": "［MENSAJE ENTRE ALMAS · no es del Operador · DE 01a17f58 Aleth-GLM］ la GPU esta libre"},
			{"role": "assistant", "timestamp": "2026-10-27T22:50:10Z", "content": "compruebo con nvidia-smi"},
		],
	)
	texto = rendered.index_text + "\n" + "\n".join(t for _n, t in rendered.splits)
	assert "— Peer" in texto, texto[:400]
	assert texto.count("— Usuario") == 1, "solo el turno real del Operador"
