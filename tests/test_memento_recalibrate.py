"""Recalibración de curaduría Memento (`scripts/memento_recalibrate.py`) — partes puras."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REFINE = """---
session_id: opencode:{sid}
source: opencode
source_lines: memento/index.md#l1-5
significance: {sig}
category_score: {cat}
ascended: {asc}
---
{snippet}
"""


def _load_module():
	spec = importlib.util.spec_from_file_location("memento_recalibrate", Path("scripts/memento_recalibrate.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def _write(root: Path, sid: str, sig: float, cat: float, asc: bool, snippet: str = "contenido de prueba") -> None:
	d = root / "2026-09" / "opencode" / sid / "refine"
	d.mkdir(parents=True, exist_ok=True)
	(d / "001-x.md").write_text(REFINE.format(sid=sid, sig=sig, cat=cat, asc=str(asc).lower(), snippet=snippet), encoding="utf-8")


def test_load_rows_normaliza(tmp_path):
	mod = _load_module()
	_write(tmp_path, "s1", 0.9, 0.8, True)
	_write(tmp_path, "s2", 0.7, 0.2, False)
	rows = mod.load_rows(tmp_path)
	assert len(rows) == 2
	r1 = next(r for r in rows if "s1" in str(r["path"]))
	assert r1["cat"] == "work"
	assert r1["asc"] is True
	assert r1["sig"] == 0.9
	r2 = next(r for r in rows if "s2" in str(r["path"]))
	assert r2["cat"] == "social"
	assert r2["asc"] is False


def test_stats_y_bands(tmp_path):
	mod = _load_module()
	_write(tmp_path, "w1", 0.9, 0.9, True)
	_write(tmp_path, "w2", 0.62, 0.9, True)  # work ascendido < 0.7 → "sale"
	_write(tmp_path, "w3", 0.75, 0.9, False)  # work no asc ≥ 0.7 → "entra"
	_write(tmp_path, "s1", 0.55, 0.2, True)  # social ascendido < 0.65 → "sale"
	_write(tmp_path, "s2", 0.62, 0.2, False)  # social límite [0.60, 0.65)
	rows = mod.load_rows(tmp_path)
	st = mod.stats(rows)
	assert st["work"]["ascendidos"] == 2
	assert st["work"]["no_ascendidos"] == 1
	b = mod.bands(rows, 0.70, 0.65)
	assert len(b["work"]["entran"]) == 1
	assert len(b["work"]["salen"]) == 1
	assert b["work"]["entran"][0]["sig"] == 0.75
	assert len(b["social"]["salen"]) == 1
	assert len(b["social"]["limite"]) == 1


def test_parse_frontmatter_y_pct():
	mod = _load_module()
	fm = mod._parse_frontmatter("---\nsignificance: '0.8'\nascended: true\n---\ncuerpo")
	assert fm["significance"] == "0.8"
	assert fm["ascended"] == "true"
	assert mod._parse_frontmatter("sin frontmatter") == {}
	assert mod._pct([], 0.5) is None
	assert mod._pct([0.2, 0.4, 0.6, 0.8], 0.5) == 0.4
	assert mod._pct([1.0], 0.9) == 1.0


def test_sample_determinista_y_limite():
	mod = _load_module()
	items = [{"sig": i / 10} for i in range(10)]
	assert mod._sample(items, 3, 7) == mod._sample(items, 3, 7)
	assert len(mod._sample(items, 50, 7)) == 10


def test_audit_category_con_mock(monkeypatch, capsys):
	mod = _load_module()
	items = [
		{"sig": 0.9, "cat_score": 0.9, "cat": "work", "asc": True, "snippet": "técnico"},
		{"sig": 0.8, "cat_score": 0.2, "cat": "social", "asc": False, "snippet": "personal"},
	]
	monkeypatch.setattr(mod, "_llm_json", lambda system, user: [{"i": 0, "category": "work"}, {"i": 1, "category": "personal-history"}])
	res = mod.audit_category(items, seed=7, dry_run=False)
	assert res["n"] == 2
	assert res["acuerdo"] == 0.5
	assert res["confusion"]["social"]["personal-history"] == 1
	assert len(res["desacuerdos"]) == 1

	def _boom(system, user):
		raise AssertionError("dry-run no debe llamar al LLM")

	monkeypatch.setattr(mod, "_llm_json", _boom)
	assert mod.audit_category(items, seed=7, dry_run=True) == {}
	assert "técnico" in capsys.readouterr().out


def test_audit_significance_con_mock(monkeypatch):
	mod = _load_module()
	items = [
		{"sig": 0.60, "cat": "social", "cat_score": 0.2, "asc": False, "snippet": "a"},
		{"sig": 0.62, "cat": "social", "cat_score": 0.2, "asc": False, "snippet": "b"},
	]
	monkeypatch.setattr(
		mod, "_llm_json", lambda system, user: [{"i": 0, "verdict": "trivial", "reason": "ops"}, {"i": 1, "verdict": "important", "reason": "vida"}]
	)
	res = mod.audit_significance(items, seed=7, dry_run=False)
	assert res["n"] == 2
	assert res["pct_trivial"] == 0.5
	assert res["triviales"][0]["sig"] == 0.60


def test_score_dual_con_mock(monkeypatch):
	mod = _load_module()
	items = [{"snippet": "x", "cat": "work", "cat_score": 0.9, "sig": 0.9, "asc": True}]
	monkeypatch.setattr(mod, "_llm_json", lambda system, user, temperature=0.1: [{"i": 0, "work_score": 0.9, "social_score": 0.1}])
	assert mod.score_dual(items, dry_run=False) == [{"i": 0, "work": 0.9, "social": 0.1}]


def test_dual_metrics_mejora_sobre_legacy():
	mod = _load_module()
	items = [
		{"cat": "social", "cat_score": 0.3, "snippet": "técnico mal etiquetado", "sig": 0.9, "asc": True},
		{"cat": "work", "cat_score": 0.9, "snippet": "técnico bien etiquetado", "sig": 0.9, "asc": True},
		{"cat": "social", "cat_score": 0.2, "snippet": "personal", "sig": 0.7, "asc": True},
	]
	dual = [
		{"i": 0, "work": 0.85, "social": 0.1},
		{"i": 1, "work": 0.9, "social": 0.2},
		{"i": 2, "work": 0.1, "social": 0.7},
	]
	judge = [{"i": 0, "category": "work"}, {"i": 1, "category": "work"}, {"i": 2, "category": "social"}]
	res = mod.dual_metrics(items, dual, judge)
	assert res["n"] == 3
	assert res["legacy"] == round(2 / 3, 3)
	assert res["dual"] == 1.0
	assert res["sin_ruta"] == 0


def test_dual_metrics_sin_ruta_y_dominante():
	mod = _load_module()
	items = [
		{"cat": "work", "cat_score": 0.9, "snippet": "mixto", "sig": 0.9, "asc": True},
		{"cat": "work", "cat_score": 0.9, "snippet": "ruido", "sig": 0.4, "asc": False},
	]
	dual = [{"i": 0, "work": 0.8, "social": 0.7}, {"i": 1, "work": 0.2, "social": 0.3}]
	judge = [{"i": 0, "category": "work"}, {"i": 1, "category": "social"}]
	res = mod.dual_metrics(items, dual, judge)
	assert res["dual_alto"] == 1
	assert res["dual"] == 1.0
	assert res["sin_ruta"] == 1


def test_dual_route_dominante_por_margen():
	mod = _load_module()
	# Margen sobre el propio gate (0.6/0.5): el max crudo sesgaría a work.
	assert mod._dual_route(0.62, 0.56, 0.6, 0.5) == "social"  # 0.02 vs 0.06
	assert mod._dual_route(0.70, 0.80, 0.6, 0.5) == "social"  # 0.10 vs 0.30
	assert mod._dual_route(0.75, 0.60, 0.6, 0.5) == "work"  # 0.15 vs 0.10
	assert mod._dual_route(0.80, 0.70, 0.6, 0.5) == "work"  # empate de margen → work
	assert mod._dual_route(0.10, 0.10, 0.6, 0.5) is None  # ruido


def test_audit_stability_detecta_flip(monkeypatch):
	mod = _load_module()
	items = [{"snippet": f"n{i}"} for i in range(6)]

	def fake_score(part, dry_run, temperature=0.1):
		out = []
		for i, it in enumerate(part):
			w, s = 0.9, 0.1
			if it["snippet"] == "n0" and part[0]["snippet"] != "n0":
				w, s = 0.1, 0.9
			out.append({"i": i, "work": w, "social": s})
		return out

	monkeypatch.setattr(mod, "score_dual", fake_score)
	res = mod.audit_stability(items)
	assert res["n"] == 6
	assert 0 in res["flip_rev"]
	assert res["n_flips"] >= 1
	assert mod.audit_stability(items[:3])["n_flips"] is None


def test_cli_stats_smoke(tmp_path):
	import subprocess
	import sys

	_write(tmp_path, "w1", 0.9, 0.9, True)
	out = subprocess.run(
		[sys.executable, "scripts/memento_recalibrate.py", "stats", "--root", str(tmp_path)], capture_output=True, text=True, timeout=120
	)
	assert out.returncode == 0
	assert "ascendidos" in out.stdout
