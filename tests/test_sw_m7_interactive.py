"""M7 single-writer — plan de refinado de engramas interactivos (D13)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
	spec = importlib.util.spec_from_file_location("interactive_refine", Path("scripts/interactive_refine.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def test_plan_elige_solo_interactivos_sin_refinar():
	mod = _load_module()
	points = [
		("a", {"node_type": "interactive_engram"}),
		("b", {"node_type": "interactive_engram", "interactive_refined": True}),
		("c", {"node_type": "memento_engram"}),
		("d", {}),
	]
	assert mod.plan_interactive(points) == ["a"]
