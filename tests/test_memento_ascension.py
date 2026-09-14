"""Tests de la ascensión curada Memento → Qdrant (RFC-002 Fase 4 §3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from red_pill.memento.ascension import ascender, parse_refine, refine_point_id

REFINE_TEXT = """---
session_id: opencode:ses_test
source: opencode
distill_ref: distill/001-x.md
source_lines: memento/index.md#l10-40
significance: 0.72
emotion: teal
intensity: 0.4
texture: {"theme": "memoria_curada", "relics": ["El archivo es Memento"]}
cross_refs: ["claude_code:ses_other"]
ascended: false
ascended_at: null
ascended_to: null
ascended_point_id: null
---

Una reflexión personal sobre el sentido de la memoria y su curaduría.
"""

WORK_REFINE_TEXT = REFINE_TEXT.replace(
	"Una reflexión personal sobre el sentido de la memoria y su curaduría.",
	"Se refactorizó el endpoint y se corrigió el bug del socket ```python```.",
)


class FakeMemoryManager:
	def __init__(self, returns: str | None = None):
		self.calls: list[dict] = []
		self._returns = returns

	def add_memory(self, **kwargs):
		self.calls.append(kwargs)
		if self._returns is not None:
			return self._returns
		return kwargs.get("point_id") or "generated-id"


class FakeRegistry:
	def __init__(self):
		self.data: dict = {}

	def get(self, source, session_id):
		return self.data.get((source, session_id))

	def upsert(self, source, session_id, entry):
		self.data.setdefault((source, session_id), {}).update(entry)


@pytest.fixture
def refine_file(tmp_path: Path) -> Path:
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "opencode-ses_test" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	f.write_text(REFINE_TEXT, encoding="utf-8")
	return f


def test_parse_refine():
	fm, body = parse_refine(REFINE_TEXT)
	assert fm["session_id"] == "opencode:ses_test"
	assert fm["significance"] == 0.72
	assert fm["texture"]["theme"] == "memoria_curada"
	assert fm["cross_refs"] == ["claude_code:ses_other"]
	assert body.startswith("Una reflexión personal")


def test_refine_point_id_is_deterministic():
	a = refine_point_id("opencode:ses_test", "memento/index.md#l10-40")
	b = refine_point_id("opencode:ses_test", "memento/index.md#l10-40")
	c = refine_point_id("opencode:ses_test", "memento/index.md#l10-41")
	assert a == b
	assert a != c


def test_ascender_promotes_to_social(refine_file: Path):
	mm, reg = FakeMemoryManager(), FakeRegistry()
	root = refine_file.parents[3]
	result = ascender(root, reg, refine_file, memory_manager=mm)

	assert result["ascended"] is True
	assert result["collection"] == "social_memories"
	assert result["point_id"] == refine_point_id("opencode:ses_test", "memento/index.md#l10-40")

	call = mm.calls[0]
	assert call["collection"] == "social_memories"
	assert call["metadata"]["session_id"] == "opencode:ses_test"
	assert call["metadata"]["origin"] == "memento"
	assert call["metadata"]["significance"] == 0.72
	assert call["importance"] == 0.72
	assert call["emotion"] == "teal"
	# idempotencia: el point id es el determinista
	assert call["point_id"] == result["point_id"]

	# sello in-place en el frontmatter del refine
	fm, _ = parse_refine(refine_file.read_text(encoding="utf-8"))
	assert fm["ascended"] is True
	assert fm["ascended_to"] == "social_memories"
	assert fm["ascended_point_id"] == result["point_id"]

	# registry actualizado
	assert reg.get("opencode", "opencode:ses_test")["ascended"] is True


def test_ascender_is_idempotent(refine_file: Path):
	mm, reg = FakeMemoryManager(), FakeRegistry()
	root = refine_file.parents[3]
	ascender(root, reg, refine_file, memory_manager=mm)
	second = ascender(root, reg, refine_file, memory_manager=mm)
	assert second["ascended"] is False
	assert second["reason"] == "already_ascended"
	assert len(mm.calls) == 1


def test_ascender_force_repromotes(refine_file: Path):
	mm, reg = FakeMemoryManager(), FakeRegistry()
	root = refine_file.parents[3]
	ascender(root, reg, refine_file, memory_manager=mm)
	forced = ascender(root, reg, refine_file, force=True, memory_manager=mm)
	assert forced["ascended"] is True
	assert len(mm.calls) == 2


def test_ascender_classifies_work(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	f.write_text(WORK_REFINE_TEXT, encoding="utf-8")
	mm = FakeMemoryManager()
	result = ascender(root, FakeRegistry(), f, memory_manager=mm)
	assert result["collection"] == "work_memories"


def test_ascender_explicit_collection(refine_file: Path):
	mm = FakeMemoryManager()
	root = refine_file.parents[3]
	result = ascender(root, FakeRegistry(), refine_file, collection="social_memories", memory_manager=mm)
	assert result["collection"] == "social_memories"


def test_ascender_missing_key(tmp_path: Path):
	d = tmp_path / "refine"
	d.mkdir()
	f = d / "bad.md"
	f.write_text("---\nsignificance: 0.9\n---\n\ncuerpo\n", encoding="utf-8")
	result = ascender(tmp_path, FakeRegistry(), f, memory_manager=FakeMemoryManager())
	assert result["ascended"] is False
	assert result["reason"] == "missing_key"


def test_ascender_rejected_by_gate(refine_file: Path):
	mm = FakeMemoryManager(returns="")
	root = refine_file.parents[3]
	result = ascender(root, FakeRegistry(), refine_file, memory_manager=mm)
	assert result["ascended"] is False
	assert result["reason"] == "rejected"
	fm, _ = parse_refine(refine_file.read_text(encoding="utf-8"))
	assert fm["ascended"] is False
