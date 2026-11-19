"""MEM-012 · F0 — la aritmética del suelo de abstención.

El instrumento decide con tres datos: dónde está el detalle, cuál es la similitud
máxima de los candidatos y si las agujas del caso existen en el corpus. Estos
tests fijan esa aritmética; la medida sobre el Búnker vive en
`scripts/mem012_floor_probe.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mem012_floor_probe.py"


def _floor_module() -> Any:
	spec = importlib.util.spec_from_file_location("mem012_floor_probe", SCRIPT)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _case(name: str, kind: str, max_sim: float, rank: Any = 1, dead: bool = False) -> Dict[str, Any]:
	return {"name": name, "kind": kind, "max_sim": max_sim, "detail_rank": rank, "dead": dead}


def test_las_agujas_que_no_existen_marcan_el_caso_como_muerto():
	fp = _floor_module()
	corpus = "el desk se siembra desde el germen y el instalador compara hashes"

	assert fp.missing_needles(corpus, ["germen", "desk"]) == []
	assert fp.missing_needles(corpus, ["germen", "pacto"]) == ["pacto"], "una aguja ausente no puede pasar nunca"


def test_el_detalle_se_busca_en_el_contenido_y_por_puesto():
	fp = _floor_module()
	rows = [
		{"rank": 1, "content": "Resumen del hub que habla de hubs"},
		{"rank": 2, "content": "El criterio vigente usa SOFT_LIMIT_KB y HARD_LIMIT_KB"},
	]

	assert fp.detail_rank(rows, ["soft_limit_kb", "hard_limit_kb"]) == 2
	assert fp.detail_rank(rows, ["no-existe"]) is None


def test_el_suelo_sale_del_hueco_entre_positivos_y_negativos():
	fp = _floor_module()
	cases = [
		_case("pos-fuerte", "must", 0.62),
		_case("pos-flojo", "must", 0.41),
		_case("neg-duro", "negative", 0.34),
		_case("neg-facil", "negative", 0.20),
	]

	cal = fp.calibrate(cases)

	assert cal["min_positive_max_sim"] == 0.41
	assert cal["max_negative_max_sim"] == 0.34
	assert round(cal["gap"], 2) == 0.07
	assert cal["floor_full_block"] == {"floor": 0.35, "positives_suppressed": 0, "negatives_blocked": 2}


def test_un_negativo_alto_obliga_a_subir_el_suelo():
	"""El suelo depende de la ventana: con 10 candidatos el negativo duro sube a
	0,39 y el 0,35 de la ventana de 3 dejaría pasar ruido."""
	fp = _floor_module()
	cases = [
		_case("pos-flojo", "must", 0.41),
		_case("neg-duro", "negative", 0.39),
		_case("neg-facil", "negative", 0.20),
	]

	cal = fp.calibrate(cases)

	# El suelo deja pasar con `>=`: un negativo en 0,39 exige 0,40 (estricto).
	assert cal["floor_full_block"]["floor"] == 0.40
	assert cal["gap"] < 0.03, "el margen se vuelve ruido: la decisión depende de la ventana"


def test_un_caso_muerto_no_entra_en_la_calibracion():
	fp = _floor_module()
	cases = [
		_case("pos-real", "must", 0.50),
		_case("pos-muerto", "must", 0.80, rank=None, dead=True),
		_case("neg", "negative", 0.30),
	]

	cal = fp.calibrate(cases)

	assert cal["positives_total"] == 1, "el caso muerto no cuenta ni como positivo ni como fallo"
	assert cal["min_positive_max_sim"] == 0.50


def test_la_tasa_por_tipo_es_la_de_c05():
	"""C-05: el negativo se abstiene siempre; los obligatorios, nunca."""
	fp = _floor_module()
	cases = [
		{"name": "pos-1", "kind": "must", "no_recall": False, "dead": False},
		{"name": "pos-2", "kind": "must", "no_recall": False, "dead": False},
		{"name": "neg-1", "kind": "negative", "no_recall": True, "dead": False},
		{"name": "neg-2", "kind": "negative", "no_recall": True, "dead": False},
		{"name": "muerto", "kind": "must", "no_recall": True, "dead": True},
	]

	rates = fp.no_recall_rates(cases)

	assert rates["must"] == {"n": 2, "no_recall": 0, "rate": 0.0}
	assert rates["negative"] == {"n": 2, "no_recall": 2, "rate": 1.0}
