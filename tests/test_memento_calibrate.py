"""Fase 4 §6.9: calibración en sombra de τ/GAIN/gate del refuerzo polaroid."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REFINE_TEXT = """---
session_id: opencode:ses_cal
source: opencode
source_lines: memento/index.md#l1-5
significance: 0.30
emotion: gray
intensity: 0.3
texture: {"theme": "tema_recurrente", "relics": ["la idea vuelve"]}
cross_refs: []
ascended: false
ascended_at: null
ascended_to: null
ascended_point_id: null
polaroid_stability: 0.0
last_reinforced_at: null
---
La idea vuelve a aparecer con regularidad mensual.
"""


def _load_module():
	spec = importlib.util.spec_from_file_location("memento_calibrate", Path("scripts/memento_calibrate.py"))
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def _write_refine(tmp_path: Path, name: str, theme: str = "tema_recurrente") -> Path:
	d = tmp_path / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True, exist_ok=True)
	f = d / f"{name}.md"
	f.write_text(REFINE_TEXT.replace("tema_recurrente", theme).replace("opencode:ses_cal", f"opencode:ses_{name}"), encoding="utf-8")
	return f


class FakeClient:
	def __init__(self, points):
		self._points = points

	def collection_exists(self, name):
		return name == "work_memories"

	def scroll(self, **kwargs):
		class Point:
			def __init__(self, payload, i):
				self.payload = payload
				self.id = f"p{i}"

		return [Point(p, i) for i, p in enumerate(self._points)], None


class FakeMM:
	def __init__(self, points):
		self.client = FakeClient(points)


class FakeReg:
	def __init__(self):
		self.state = {"registry": {}}

	def save(self):
		pass


def test_calibrate_reports_matrix(tmp_path: Path):
	mod = _load_module()
	_write_refine(tmp_path, "a")
	# 3 apariciones del tema en 3 ciclos consecutivos → 3 refuerzos con decay+GAIN.
	base = 1_800_000_000.0
	engramas = [
		{"texture": {"theme": "tema_recurrente"}, "created_at": base},
		{"texture": {"theme": "tema_recurrente"}, "created_at": base + 24 * 3600},
		{"texture": {"theme": "tema_recurrente"}, "created_at": base + 48 * 3600},
	]
	mm = FakeMM(engramas)
	result = mod.calibrate(
		root=tmp_path, registry=FakeReg(), memory_manager=mm, window_hours=24, n_cycles=30, tau_grid=(90.0,), gain_grid=(1.0,), gate_grid=(1.5, 5.0)
	)
	assert result["refine_count"] == 1
	assert result["engramas"] == 3
	by_gate = {r["gate"]: r["ascensos"] for r in result["matrix"]}
	assert by_gate[1.5] == 1  # 3 refuerzos → S≈2.78 ≥ 1.5
	assert by_gate[5.0] == 0  # gate provisional (5.0) → no en 3 apariciones
