"""Troceado del etiquetado: el ánimo de un texto largo no es el de su primera frase.

El turno se recortaba a `MAX_CHARS` cogiendo cabeza y cola. Con respuestas de
2.281 chars de mediana (medido 2026-11-20), el medio no se etiquetaba nunca y el
tag salía `degraded: truncated`. Ahora se trocea con solape y se agrega.
"""

from __future__ import annotations

from red_pill.core.realtime_tag import aggregate_tags, split_chunks


def test_texto_corto_no_se_trocea():
	assert split_chunks("hola", 300) == ["hola"]


def test_trocea_respetando_el_tope_y_con_solape():
	texto = " ".join(f"palabra{i}" for i in range(400))
	trozos = split_chunks(texto, 300)
	assert len(trozos) > 1
	assert all(len(t) <= 300 for t in trozos)
	# el solape evita perder la frase que cae justo en el corte
	assert trozos[0][-20:] in texto and trozos[1][:20] in texto


def test_agrega_por_confianza_acumulada():
	tags = [
		{"tag_status": "ok", "tag_emotion": "calm", "tag_theme": "work", "tag_confidence": 0.9},
		{"tag_status": "ok", "tag_emotion": "tense", "tag_theme": "work", "tag_confidence": 0.4},
	]
	out = aggregate_tags(tags)
	assert out["tag_emotion"] == "calm"
	assert out["tag_confidence"] == 0.9, "la confianza del ganador es su mayor evidencia"
	assert out["tag_chunks"] == 2


def test_dos_trozos_de_la_misma_emocion_suman():
	tags = [
		{"tag_status": "ok", "tag_emotion": "tense", "tag_theme": "work", "tag_confidence": 0.6},
		{"tag_status": "ok", "tag_emotion": "tense", "tag_theme": "work", "tag_confidence": 0.6},
		{"tag_status": "ok", "tag_emotion": "calm", "tag_theme": "work", "tag_confidence": 0.9},
	]
	assert aggregate_tags(tags)["tag_emotion"] == "tense"


def test_si_todo_falla_lo_dice():
	out = aggregate_tags([{"tag_status": "failed", "tag_reason": "sidecar-down"}])
	assert out["tag_status"] == "failed"
	assert out["tag_reason"] == "sidecar-down"
