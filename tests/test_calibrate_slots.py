"""Receta de slots: recomendación por plateau (sin GPU)."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def mod():
	p = Path(__file__).parent.parent / "scripts" / "calibrate_slots.py"
	spec = importlib.util.spec_from_file_location("calibrate_slots", p)
	m = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(m)
	return m


def test_recomienda_el_plateau(mod):
	rows = [
		{"slots": 1, "speedup": 1.0},
		{"slots": 2, "speedup": 2.1},
		{"slots": 4, "speedup": 2.6},
		{"slots": 6, "speedup": 2.64},
		{"slots": 8, "speedup": 2.88},
	]
	assert mod.recommend(rows, min_gain=0.10) == 4


def test_dry_run_no_toca_gpu(mod, capsys):
	assert mod.main(["--dry-run", "--profile", "bonsai_2_9b"]) == 0
	out = capsys.readouterr().out
	assert "dry-run" in out and "slots=" in out
