"""M1 single-writer — ascensión con DOS fechas + node_type + dedup-at-ascension.

Fija lo del hito 1: el engrama ascendido lleva `created_at` = fecha real de la
sesión (no la de ascensión) + `ascended_at` + `node_type`; y el dedup
(`SW_DEDUP_ENABLED`) asciende UN ganador determinista por grupo.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from red_pill.memento.ascension import _pick_ascension_winner, ascend_by_threshold, ascender

REFINE = """---
session_id: opencode:ses_test
source: opencode
source_lines: memento/index.md#l10-40
significance: {sig}
category_score: 0.8
texture: {{"theme": "t", "relics": []}}
ascended: false
ascended_at: null
ascended_to: null
ascended_point_id: null
---

{body}
"""


class FakeMM:
	def __init__(self):
		self.calls: list[dict] = []

	def add_memory(self, **kwargs):
		self.calls.append(kwargs)
		return kwargs.get("point_id") or "id"


class FakeReg:
	def __init__(self, state=None):
		self.state = state if state is not None else {"registry": {}}
		self.saved = False

	def upsert(self, *args, **kwargs):
		pass

	def save(self):
		self.saved = True


def _write(root: Path, rel: str, text: str) -> Path:
	p = root / rel
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(text, encoding="utf-8")
	return p


def test_ascender_fija_fecha_de_sesion_y_node_type(tmp_path: Path):
	root = tmp_path / "m"
	f = _write(root, "2026-09/opencode/s/refine/001-x.md", REFINE.format(sig=0.8, body="cuerpo uno"))
	state = {"registry": {"opencode": {"opencode:ses_test": {"created_at": "2026-08-12T20:35:06.300000Z"}}}}
	mm = FakeMM()
	result = ascender(root, FakeReg(state), f, memory_manager=mm)

	assert result["ascended"] is True
	call = mm.calls[0]
	assert call["metadata"]["node_type"] == "memento_engram"
	assert call["metadata"]["ascended_at"]
	expected = datetime.datetime.fromisoformat("2026-08-12T20:35:06.300000+00:00").timestamp()
	assert call["created_at"] is not None and abs(call["created_at"] - expected) < 1


def test_ascender_sin_registry_no_fuerza_fecha(tmp_path: Path):
	root = tmp_path / "m"
	f = _write(root, "2026-09/opencode/s/refine/001-x.md", REFINE.format(sig=0.8, body="cuerpo"))
	mm = FakeMM()
	ascender(root, FakeReg(), f, memory_manager=mm)
	assert mm.calls[0]["created_at"] is None


def test_pick_winner_determinista_por_significance_y_cuerpo():
	e_low = (Path("a"), {"category_score": 0.5}, "cuerpo corto", 0.6)
	e_high = (Path("b"), {"category_score": 0.5}, "cuerpo corto", 0.9)
	e_long = (Path("c"), {"category_score": 0.5}, "cuerpo muchísimo más largo", 0.6)
	assert _pick_ascension_winner([e_low, e_high, e_long]) is e_high  # gana mayor significance


def test_dedup_asciende_solo_un_ganador(tmp_path: Path, monkeypatch):
	import red_pill.config as cfgmod

	root = tmp_path / "m"
	body = "mismo cuerpo duplicado"
	_write(root, "2026-09/opencode/s/refine/001-a.md", REFINE.format(sig=0.9, body=body))
	_write(root, "2026-09/opencode/s/refine/002-b.md", REFINE.format(sig=0.6, body=body))
	mm = FakeMM()
	monkeypatch.setattr(cfgmod, "SW_DEDUP_ENABLED", True, raising=False)

	stats = ascend_by_threshold(root, FakeReg(), memory_manager=mm)
	assert stats["ascendidos"] == 1
	assert stats["duplicados_omitidos"] == 1
	assert mm.calls[0]["metadata"]["significance"] == 0.9


def test_sin_dedup_asciende_ambos(tmp_path: Path, monkeypatch):
	import red_pill.config as cfgmod

	root = tmp_path / "m"
	body = "mismo cuerpo duplicado"
	_write(root, "2026-09/opencode/s/refine/001-a.md", REFINE.format(sig=0.9, body=body))
	_write(root, "2026-09/opencode/s/refine/002-b.md", REFINE.format(sig=0.6, body=body))
	mm = FakeMM()
	monkeypatch.setattr(cfgmod, "SW_DEDUP_ENABLED", False, raising=False)

	stats = ascend_by_threshold(root, FakeReg(), memory_manager=mm)
	assert stats["ascendidos"] == 2
	assert stats["duplicados_omitidos"] == 0


def test_dedup_no_colapsa_multi_idea(tmp_path: Path, monkeypatch):
	"""Mismo (session_id, source_lines) con CUERPOS distintos = ideas distintas."""
	import red_pill.config as cfgmod

	root = tmp_path / "m"
	_write(root, "2026-09/opencode/s/refine/001-a.md", REFINE.format(sig=0.9, body="idea A"))
	_write(root, "2026-09/opencode/s/refine/002-b.md", REFINE.format(sig=0.8, body="idea B"))
	mm = FakeMM()
	monkeypatch.setattr(cfgmod, "SW_DEDUP_ENABLED", True, raising=False)

	stats = ascend_by_threshold(root, FakeReg(), memory_manager=mm)
	assert stats["ascendidos"] == 2  # ambas ascienden (no son duplicados)
	assert stats["duplicados_omitidos"] == 0
