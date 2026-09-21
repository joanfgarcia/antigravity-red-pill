"""M3 single-writer — dedup de duplicados sembrados (MEM-006 P1-B)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
	spec = importlib.util.spec_from_file_location("memento_dedup_qdrant", Path("scripts/memento_dedup_qdrant.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def test_plan_deja_un_superviviente_por_cuerpo():
	mod = _load_module()
	points = [
		("p1", {"origin": "memento", "session_id": "opencode:ses_a", "source_lines": "m#l1-5", "content": "cuerpo", "significance": 0.6}),
		("p2", {"origin": "memento", "session_id": "opencode:ses_a", "source_lines": "m#l1-5", "content": "cuerpo", "significance": 0.9}),
		("p3", {"origin": "memento", "session_id": "opencode:ses_a", "source_lines": "m#l1-5", "content": "otra idea distinta", "significance": 0.7}),
	]
	plan = mod.plan_dedup(points)
	# p1/p2 son el mismo cuerpo → se va p1 (menor significance); p3 es multi-idea legítima, se queda.
	assert plan["to_delete"] == ["p1"]


def test_plan_no_toca_no_memento_ni_singletons():
	mod = _load_module()
	points = [
		("p1", {"origin": "interactive", "content": "x"}),
		("p2", {"origin": "memento", "session_id": "s", "source_lines": "l", "content": "único", "significance": 0.5}),
	]
	plan = mod.plan_dedup(points)
	assert plan["to_delete"] == []
