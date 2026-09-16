"""Fase 4 (2026-09-14): limpieza y resiembra de work/social_memories desde Memento."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REFINE_TEXT = """---
session_id: opencode:ses_reseed
source: opencode
source_lines: memento/index.md#l1-5
significance: {sig}
emotion: gray
intensity: 0.3
texture: {{"theme": "tema_reseed", "relics": []}}
cross_refs: []
ascended: false
ascended_at: null
ascended_to: null
ascended_point_id: null
polaroid_stability: 0.0
last_reinforced_at: null
---
{body}
"""


def _load_module():
	spec = importlib.util.spec_from_file_location("memento_reseed", Path("scripts/memento_reseed.py"))
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


class FakeReg:
	def __init__(self):
		self.state = {"registry": {}}


def _write_refine(tmp_path: Path, name: str, sig: float, body: str) -> Path:
	d = tmp_path / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True, exist_ok=True)
	f = d / f"{name}.md"
	f.write_text(REFINE_TEXT.format(sig=sig, body=body).replace("opencode:ses_reseed", f"opencode:ses_{name}"), encoding="utf-8")
	return f


def test_reseed_plan_counts_by_collection(tmp_path: Path):
	mod = _load_module()
	_write_refine(tmp_path, "a", 0.8, "Una reflexión personal y serena sobre el descanso.")
	_write_refine(tmp_path, "b", 0.9, "Se corrigió el bug del socket ```python``` y se refactorizó el endpoint.")
	_write_refine(tmp_path, "c", 0.2, "Rutina trivial sin valor durable.")
	plan = mod._plan(tmp_path, FakeReg(), min_significance=0.5)
	assert plan["no_ascendidos"] == 3
	assert plan["por_coleccion"] == {"work_memories": 1, "social_memories": 1}  # la de sig 0.2 no cuenta
	assert plan["por_fuente"]["opencode"] == 2


def test_reseed_plan_respects_gate(tmp_path: Path):
	mod = _load_module()
	_write_refine(tmp_path, "a", 0.6, "Texto técnico con ```python``` y refactor de servicios.")
	_write_refine(tmp_path, "b", 0.4, "Otra reflexión personal sobre el tiempo.")
	plan = mod._plan(tmp_path, FakeReg(), min_significance=0.5)
	assert plan["por_coleccion"] == {"work_memories": 1}  # solo la sig>=0.5
