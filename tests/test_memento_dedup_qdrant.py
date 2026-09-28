"""P1-B (MEM-006): dedup de Qdrant — partes puras (plan, score, reglas duras)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
	spec = importlib.util.spec_from_file_location("memento_dedup_qdrant", Path("scripts/memento_dedup_qdrant.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def _p(
	pid,
	coll="work_memories",
	content="Joan me pide arreglar el endpoint de auth y lo despliego",
	sig=0.8,
	engine="granite_8b",
	sid="s1",
	lines="memento/index.md#l1-5",
	**extra,
):
	payload = {
		"content": content,
		"significance": sig,
		"engine": engine,
		"session_id": sid,
		"source_lines": lines,
		"work_score": 0.9,
		"social_score": 0.1,
		"intensity": 0.7,
	}
	payload.update(extra)
	return {"id": pid, "collection": coll, "payload": payload}


def test_plan_deduplica_por_body_y_prefiere_granite():
	mod = _load_module()
	points = [
		_p("a", engine="tiny_aya_water", sig=0.9),
		_p("b", engine="granite_8b", sig=0.7),
	]
	plan = mod.build_plan(points)
	assert plan["totals"]["grupos_dup"] == 1
	assert plan["totals"]["borrados_planificados"] == 1
	group = plan["groups"][0]
	assert group["survivor"]["id"] == "b"  # engine granite gana pese a menor significance
	assert [loser["id"] for loser in group["losers"]] == ["a"]


def test_empate_por_significance_y_id():
	mod = _load_module()
	points = [
		_p("a", sig=0.6),
		_p("b", sig=0.9),
		_p("c", sig=0.9),
	]
	plan = mod.build_plan(points)
	group = plan["groups"][0]
	assert group["survivor"]["id"] == "b"  # empate de score → significance; empate → id


def test_referencia_protege_al_perdedor():
	mod = _load_module()
	points = [
		_p("a", engine="tiny_aya_water", sig=0.9),
		_p("b", engine="granite_8b", sig=0.7),
		_p("hub", node_type="synthesis_hub", content="hub", associations=["a"], sig=0.1),
	]
	plan = mod.build_plan(points)
	group = plan["groups"][0]
	assert group["protected"] is True
	assert group["survivor"]["id"] == "a"  # referenciado gana aunque puntúe menos
	assert [loser["id"] for loser in group["losers"]] == ["b"]


def test_sin_clave_no_se_toca():
	mod = _load_module()
	points = [
		_p("a", sid="", lines=""),
		_p("b", sid="", lines=""),
	]
	plan = mod.build_plan(points)
	assert plan["totals"]["grupos_dup"] == 0
	assert plan["totals"]["sin_clave"] == 2


def test_body_distinto_no_deduplica():
	mod = _load_module()
	points = [
		_p("a", content="texto uno distinto"),
		_p("b", content="texto dos distinto"),
	]
	plan = mod.build_plan(points)
	assert plan["totals"]["grupos_dup"] == 0
	assert plan["totals"]["fuentes_con_body_distinto"] == 1


def test_scope_collection_ignora_source_lines():
	mod = _load_module()
	a = _p("a", lines="memento/index.md#l1-5")
	b = _p("b", lines="memento/index.md#l9-20")
	plan = mod.build_plan([a, b], scope="collection")
	assert plan["totals"]["grupos_dup"] == 1
	assert plan["totals"]["borrados_planificados"] == 1


def test_scope_global_prefiere_coleccion_enrutada():
	mod = _load_module()
	content = "Joan me pide arreglar el endpoint de auth y lo despliego"
	work = _p("w", coll="work_memories", content=content, engine="tiny_aya_water", sig=0.9)
	social = _p("s", coll="social_memories", content=content, engine="granite_8b", sig=0.7)
	plan = mod.build_plan([work, social], scope="global", route_resolver=lambda point: "social_memories")
	group = plan["groups"][0]
	assert group["survivor"]["id"] == "s"  # la ruta de la nota manda sobre engine/significance
	assert plan["totals"]["survivores_con_ruta_ok"] == 1
	assert plan["totals"]["borrados_planificados"] == 1


def test_deletions_by_collection_usa_la_del_perdedor():
	"""Regresión: los borrados cruzados van a la colección del PERDEDOR."""
	mod = _load_module()
	content = "Joan me pide arreglar el endpoint de auth y lo despliego"
	work = _p("w", coll="work_memories", content=content)
	social = _p("s", coll="social_memories", content=content)
	plan = mod.build_plan([work, social], scope="global", route_resolver=lambda point: "work_memories")
	by_coll = mod.deletions_by_collection(plan)
	assert by_coll == {"social_memories": ["s"]}
