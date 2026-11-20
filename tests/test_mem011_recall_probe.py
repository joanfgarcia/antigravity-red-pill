"""Tests de la sonda de calidad del recall (`scripts/mem011_recall_probe.py`).

La sonda mide el puesto del detalle esperado sobre lo que el recall devuelve de
verdad. Lo que se fija aquí es la **aritmética del juicio**, que es donde una
sonda se miente a sí misma: contar un hit por el snippet recortado, ordenar por
score cuando la abstención se decide por similitud, o tratar el control negativo
como un caso de detalle.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "mem011_recall_probe.py"


def _load():
	spec = importlib.util.spec_from_file_location("mem011_recall_probe_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = mod
	spec.loader.exec_module(mod)
	return mod


def _row(rank, content, similarity=0.5):
	return {"rank": rank, "content": content, "snippet": content[:20], "similarity": similarity, "score": 0.8}


def test_detalle_por_contenido_completo_no_por_snippet():
	mod = _load()
	rows = [_row(1, "hub que habla de documentos"), _row(2, "criterio vigente: soft_limit_kb y hard_limit_kb")]
	assert mod.detail_rank(rows, ["soft_limit_kb", "hard_limit_kb"]) == 2


def test_detalle_exige_todas_las_agujas():
	mod = _load()
	rows = [_row(1, "solo soft_limit_kb"), _row(2, "nada")]
	assert mod.detail_rank(rows, ["soft_limit_kb", "hard_limit_kb"]) is None


def test_control_negativo_no_tiene_detalle():
	mod = _load()
	rows = [_row(1, "paella valenciana")]
	assert mod.detail_rank(rows, []) is None
	assert mod.detail_rank([], ["paella"]) is None


def test_resumen_toma_similitud_del_primero_y_redondea():
	mod = _load()
	summary = mod.summarize("ciego", [_row(1, "x", similarity=0.5521)], ["x"], 1117.24)
	assert summary["detail_rank"] == 1
	assert summary["top"] == 0.5521
	assert summary["top_source"] == "payload"
	assert summary["ms"] == 1117.2
	assert summary["hits"] == 1
	assert mod.summarize("vacio", [], ["x"], 1.0)["top"] is None


def test_resumen_sin_similitud_en_payload_lo_dice():
	mod = _load()
	summary = mod.summarize("negativo", [{"rank": 1, "content": "paella", "similarity": None, "score": 0.189}], [], 1.0)
	assert summary["top"] == 0.189
	assert summary["top_source"] == "score"


def test_filas_normalizan_payload_y_sesion():
	mod = _load()

	class _Hit:
		def __init__(self):
			self.id = "abc"
			self.score = 0.81234
			self.payload = {"content": "linea uno\nlinea dos", "node_type": "synthesis_hub", "session": "opencode:ses_x", "similarity": 0.4}

	rows = mod.case_rows([_Hit()])
	assert rows[0]["rank"] == 1
	assert rows[0]["score"] == 0.8123
	assert rows[0]["title"] == "linea uno"
	assert rows[0]["session"] == "opencode:ses_x"
	assert rows[0]["content_len"] == len("linea uno\nlinea dos")


def test_fichero_de_casos_es_el_medido_y_tiene_control_negativo():
	mod = _load()
	cases = mod.load_cases(REPO_ROOT / "scripts" / "mem011_recall_cases.json")
	assert len(cases) == 11
	assert len({c["name"] for c in cases}) == 11
	negative = [c for c in cases if c["kind"] == "negative"]
	assert len(negative) == 1 and negative[0]["expect"] == []
	assert all(c["collection"].endswith("memories") for c in cases)


def test_caso_sin_campos_obligatorios_aborta():
	mod = _load()
	path = Path(__file__).with_name("_tmp_cases_bad.json")
	path.write_text(json.dumps({"cases": [{"name": "x", "query": "y"}]}), encoding="utf-8")
	try:
		mod.load_cases(path)
	except SystemExit as exc:
		assert "collection" in str(exc)
	else:  # pragma: no cover
		raise AssertionError("un caso incompleto debe abortar")
	finally:
		path.unlink()
