"""MEM-012 · F1 — la confianza se decide sobre la similitud, no sobre la utilidad.

Las bandas salen de F0 (35 casos, camino real): insuficiente < 0,38 (suelo
ratificado) · baja < 0,4551 (p10) · media < 0,592 (p25) · alta ≥ 0,592.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from red_pill.config import get_config_cached
from red_pill.recall_abstention import (
	HIGH,
	INSUFFICIENT,
	LOW,
	MEDIUM,
	confidence,
	is_below_floor,
	max_similarity,
	similarity,
)


def _hit(score: float, **payload) -> SimpleNamespace:
	return SimpleNamespace(score=score, payload=dict(payload))


def test_las_bandas_son_las_medidas_en_f0():
	assert confidence(0.20) == INSUFFICIENT
	assert confidence(0.40) == LOW
	assert confidence(0.50) == MEDIUM
	assert confidence(0.60) == HIGH


def test_los_cortes_dejan_pasar():
	"""`>=`: exactamente en el suelo no es insuficiente; en media/alta sube."""
	assert confidence(0.38) == LOW
	assert confidence(0.4551) == MEDIUM
	assert confidence(0.592) == HIGH
	assert is_below_floor(0.3799) is True
	assert is_below_floor(0.38) is False


def test_la_similitud_es_el_score_no_la_utilidad():
	hit = _hit(0.53, reinforcement_score=9.0)

	assert similarity(hit) == pytest.approx(0.53), "la utilidad (0-10) no es relevancia"


def test_el_maximo_se_toma_sobre_la_ventana_no_sobre_el_top1():
	"""El caso `handshake-s6`: top1 0,19 y max 0,83 en la misma consulta."""
	hits = [_hit(0.1902), _hit(0.833), _hit(0.4)]

	assert max_similarity(hits) == pytest.approx(0.833)
	assert confidence(max_similarity(hits)) == HIGH


def test_sin_hits_la_confianza_es_insuficiente():
	assert max_similarity([]) == 0.0
	assert confidence(max_similarity([])) == INSUFFICIENT


def test_un_negativo_con_similitud_negativa_es_insuficiente():
	assert confidence(-0.0215) == INSUFFICIENT


def test_los_cortes_son_configurables():
	"""Cambiar el número no es cambiar la lógica (D-AB-02/D-AB-05)."""
	assert confidence(0.42, floor=0.45) == INSUFFICIENT
	assert confidence(0.42, floor=0.40, media=0.41, alta=0.50) == MEDIUM


def test_los_defaults_de_config_son_los_ratificados():
	cfg = get_config_cached()

	assert cfg.SW_RECALL_ABSTENTION_FLOOR == 0.38
	assert cfg.SW_RECALL_CONFIDENCE_MEDIA == 0.4551
	assert cfg.SW_RECALL_CONFIDENCE_ALTA == 0.592
