"""MEM-012 · F2 — el objeto `no_recall` y las dos posturas.

D-AB-03: no se oculta nada (los hits que alcanzan el suelo viajan con su
similitud; los demás viajan como cuenta). D-AB-04: la banda baja se materializa
solo con `include_below_floor`. I-06: el suelo se aplica al presentar, nunca al
recuperar. C-07: apagarlo (`floor=0`) no abstiene nunca. I-03: las directivas no
cambian de comportamiento.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from red_pill.recall_abstention import (
	HIGH,
	INSUFFICIENT,
	LOW,
	alternatives_for,
	build_abstention,
	passes_injection,
)


def _hit(point_id: str, score: float, content: str = "texto", **payload: Any) -> SimpleNamespace:
	return SimpleNamespace(id=point_id, score=score, payload={"content": content, **payload})


def _searched() -> dict:
	return {"collection": "work_memories", "strategy": "hybrid", "anchors": ["paella"]}


def test_paella_no_recall_y_no_materializa_la_banda_por_defecto():
	hits = [_hit("a", 0.2122), _hit("b", 0.16), _hit("c", -0.02)]

	obj = build_abstention(hits, collection="work_memories", floor=0.38, searched=_searched())

	assert obj["no_recall"] is True
	assert obj["confidence"] == INSUFFICIENT
	assert obj["hits"] == [], "nada alcanza el suelo: no se inyecta"
	assert obj["below_floor_count"] == 3, "la cuenta viaja siempre (D-AB-04)"
	assert "below_floor" not in obj, "la banda solo se materializa con la puerta explícita"
	assert "replantear" in obj["alternatives"]


def test_la_inspeccion_materializa_la_misma_gente_marcada():
	hits = [_hit("a", 0.2122), _hit("b", 0.16), _hit("c", -0.02)]

	obj = build_abstention(hits, collection="work_memories", floor=0.38, include_below_floor=True, searched=_searched())

	assert {row["id"] for row in obj["below_floor"]} == {"a", "b", "c"}, "no inventa ni pierde (C-06)"
	assert all(row["confidence"] == INSUFFICIENT for row in obj["below_floor"])


def test_un_acierto_bajo_pero_sobre_el_suelo_no_se_abstiene():
	"""`Rocky` medido: 0,3971 → pasa el suelo y viaja como `baja`."""
	obj = build_abstention([_hit("rocky", 0.3971)], collection="social_memories", floor=0.38, searched=_searched())

	assert obj["no_recall"] is False
	assert obj["confidence"] == LOW
	assert [row["id"] for row in obj["hits"]] == ["rocky"]
	assert "memento_fulltext" in obj["alternatives"], "C-04: baja ofrece la búsqueda literal"


def test_alta_no_ofrece_alternativas():
	obj = build_abstention([_hit("x", 0.70)], collection="work_memories", floor=0.38, searched=_searched())

	assert obj["confidence"] == HIGH
	assert obj["no_recall"] is False
	assert obj["alternatives"] == []


def test_suelo_cero_nunca_se_abstiene():
	"""C-07: con floor=0 el sistema se comporta como hoy, incluso con similitud negativa."""
	obj = build_abstention([_hit("x", -0.02)], collection="work_memories", floor=0.0, searched=_searched())

	assert obj["no_recall"] is False
	assert obj["below_floor_count"] == 0
	assert [row["id"] for row in obj["hits"]] == ["x"]


def test_las_directivas_quedan_exentas():
	"""I-03: una directiva floja no cambia de comportamiento."""
	obj = build_abstention([_hit("d", 0.10, immune=True)], collection="directive_memories", floor=0.38, exempt=True, searched=_searched())

	assert obj["no_recall"] is False
	assert [row["id"] for row in obj["hits"]] == ["d"]
	assert obj["below_floor_count"] == 0


def test_sin_hits_es_no_recall_insuficiente():
	obj = build_abstention([], collection="work_memories", floor=0.38, searched=_searched())

	assert obj["no_recall"] is True
	assert obj["confidence"] == INSUFFICIENT
	assert obj["max_similarity"] == 0.0


def test_alternativas_por_banda():
	assert alternatives_for(INSUFFICIENT) == ["memento_fulltext", "replantear", "ampliar"]
	assert alternatives_for(LOW) == ["memento_fulltext", "ampliar"]
	assert alternatives_for(HIGH) == []


def test_la_inyeccion_nunca_es_mas_laxa_que_el_suelo():
	# Un hit flojo no entra; uno que lo alcanza sí.
	assert passes_injection(0.30, floor=0.38, intent_threshold=0.0) is False
	assert passes_injection(0.40, floor=0.38, intent_threshold=0.0) is True
	# El umbral de intención manda si es más alto.
	assert passes_injection(0.40, floor=0.38, intent_threshold=0.5) is False
	assert passes_injection(0.55, floor=0.38, intent_threshold=0.5) is True
	# I-03: los inmunes se eximen del suelo NUEVO, pero conservan su umbral de
	# intención (comportamiento de antes).
	assert passes_injection(0.60, floor=0.70, intent_threshold=0.5, immune=True) is True
	assert passes_injection(0.60, floor=0.70, intent_threshold=0.5) is False
	assert passes_injection(0.10, floor=0.38, intent_threshold=0.5, immune=True) is False
	assert passes_injection(0.10, floor=0.38, intent_threshold=0.0, immune=True) is True
	# C-07: apagado el suelo y la intención, puerta abierta (incluso con similitud negativa).
	assert passes_injection(-0.02, floor=0.0, intent_threshold=0.0) is True
