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
