"""Rescore notes-first (annotate) + reparación legacy de refine — partes puras."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from red_pill.memento.registry import MementoRegistry

NOTE = """---
session_id: opencode:s1
source: opencode
source_lines: memento/index.md#l1-5
split_ref: memento/index.md#l1-5
distill_ref: 2026-09/opencode/s1/distill/001-x.md
title: Idea
significance: 0.9
emotion: gray
intensity: 0.5
texture: {{"theme": "t", "relics": []}}
work_score: 0.40
social_score: 0.10
dual_route: none
quality_flags: []
engine: granite_8b
prompt_version: v1
ascended: {ascended}
---
Cuerpo de la nota sobre el endpoint.
"""


def _load_module():
	spec = importlib.util.spec_from_file_location("memento_refine_rescore", Path("scripts/memento_refine_rescore.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def _tree(tmp_path, ascended=False, with_note=True):
	root = tmp_path / "memento"
	dir_rel = "2026-09/opencode/s1"
	d = root / dir_rel
	(d / "distill").mkdir(parents=True)
	(d / "distill" / "001-x.md").write_text("---\nsection: 001\n---\nResumen.\n", encoding="utf-8")
	if with_note:
		(d / "annotate").mkdir()
		(d / "annotate" / "001-idea.md").write_text(NOTE.format(ascended="true" if ascended else "false"), encoding="utf-8")
	reg = MementoRegistry(path=tmp_path / "reg.json")
	reg.upsert("opencode", "opencode:s1", {"dir": dir_rel, "memento_hash": "h", "message_count": 5})
	return root, reg, dir_rel


def test_list_pending_notes_first(tmp_path):
	mod = _load_module()
	root, reg, dir_rel = _tree(tmp_path)
	assert mod.list_pending(reg, root, target="notes") == [dir_rel]
	# con notas → el target refines (legacy) NO la toca (manda la nota)
	assert mod.list_pending(reg, root, target="refines") == []


def test_process_one_notas_actualiza_frontmatter(tmp_path):
	mod = _load_module()
	root, reg, dir_rel = _tree(tmp_path)

	def transport(system, user, max_tokens):
		return json.dumps([{"i": 0, "work_score": 0.9, "social_score": 0.05}])

	result = mod.process_one(root, reg, dir_rel, target="notes", transport=transport)
	assert result["notas_candidatas"] == 1
	assert result["resueltas"] == 1
	text = (root / dir_rel / "annotate" / "001-idea.md").read_text(encoding="utf-8")
	assert "dual_route: work" in text
	assert "work_score: 0.90" in text
	assert "social_score: 0.05" in text


def test_notas_ascendidas_no_se_tocan(tmp_path):
	mod = _load_module()
	root, reg, dir_rel = _tree(tmp_path, ascended=True)
	assert mod.list_pending(reg, root, target="notes") == []
	result = mod.process_one(root, reg, dir_rel, target="notes", transport=lambda *args: "[]")
	assert result.get("skipped") is True


def test_refines_sin_notas_es_el_fallback(tmp_path):
	mod = _load_module()
	root, reg, dir_rel = _tree(tmp_path, with_note=False)
	assert mod.list_pending(reg, root, target="notes") == []
	assert mod.list_pending(reg, root, target="refines") == [dir_rel]


def test_limit_acota_el_listado(tmp_path):
	mod = _load_module()
	root, reg, dir_rel = _tree(tmp_path)
	# segunda sesión con nota pendiente
	d2 = root / "2026-09/opencode/s2"
	(d2 / "distill").mkdir(parents=True)
	(d2 / "distill" / "001-x.md").write_text("---\nsection: 001\n---\nResumen.\n", encoding="utf-8")
	(d2 / "annotate").mkdir()
	(d2 / "annotate" / "001-idea.md").write_text(NOTE.format(ascended="false"), encoding="utf-8")
	reg.upsert("opencode", "opencode:s2", {"dir": "2026-09/opencode/s2", "memento_hash": "h2", "message_count": 3})
	assert len(mod.list_pending(reg, root, target="notes")) == 2
	assert len(mod.list_pending(reg, root, target="notes", limit=1)) == 1
