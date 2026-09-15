"""Tests de la ascensión curada Memento → Qdrant (RFC-002 Fase 4 §3)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from red_pill.memento.ascension import (
	_temas_afines,
	ascend_by_threshold,
	ascender,
	parse_refine,
	polaroid_decay,
	refine_point_id,
	reinforce_refine,
	weave_memento_reinforcement,
)

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
polaroid_stability: 0.0
last_reinforced_at: null
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

	def save(self):
		pass


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
	assert call["importance"] == pytest.approx(3.6)  # curado: 0.72 × 5 → erode lento
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


# --- Clasificación work/social por LLM (ratio category_score, 2026-09-14) ---


def _write_refine_with_score(tmp_path: Path, name: str, score: float | None, body: str) -> Path:
	d = tmp_path / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True, exist_ok=True)
	f = d / f"{name}.md"
	text = (
		REFINE_TEXT.replace("opencode:ses_test", f"opencode:ses_{name}")
		.replace('texture: {"theme": "memoria_curada"', 'texture: {"theme": "cat_score"')
		.replace("Una reflexión personal sobre el sentido de la memoria y su curaduría.", body)
	)
	if score is not None:
		text = text.replace("last_reinforced_at: null\n---", f"last_reinforced_at: null\ncategory_score: {score}\n---")
	f.write_text(text, encoding="utf-8")
	return f


def test_ascender_uses_category_score_from_frontmatter(tmp_path: Path):
	root = tmp_path / "memento"
	f_work = _write_refine_with_score(root, "w", 0.9, "Refactor técnico del endpoint.")
	f_social = _write_refine_with_score(root, "s", 0.1, "Reflexión personal serena.")
	mm = FakeMemoryManager()
	assert ascender(root, FakeRegistry(), f_work, memory_manager=mm)["collection"] == "work_memories"
	assert ascender(root, FakeRegistry(), f_social, memory_manager=mm)["collection"] == "social_memories"


def test_ascender_uses_curator_score_over_transport(tmp_path: Path):
	"""El score del curador (frontmatter) manda; el LLM standalone es débil
	(tiny_aya da 0.0 siempre) y NO se usa como fallback automático."""
	import json

	root = tmp_path / "memento"
	f_work = _write_refine_with_score(root, "w", 0.9, "Refactor técnico del endpoint.")

	def llm_transport(system, user, max_tokens):
		return json.dumps({"category_score": 0.0})  # standalone falla, pero no debe usarse

	mm = FakeMemoryManager()
	result = ascender(root, FakeRegistry(), f_work, memory_manager=mm, transport=llm_transport)
	assert result["collection"] == "work_memories"  # 0.9 del curador, no 0.0 del standalone
	assert mm.calls[0]["metadata"].get("category_score") == 0.9


def test_ascender_falls_back_to_heuristic_without_llm(tmp_path: Path):
	root = tmp_path / "memento"
	f = _write_refine_with_score(root, "h", None, "Una idea personal y tranquila.")
	result = ascender(root, FakeRegistry(), f, memory_manager=FakeMemoryManager())
	assert result["collection"] == "social_memories"  # heurística: ambigüedad → social


def test_category_from_score_threshold():
	from red_pill.memento.ascension import _category_from_score

	assert _category_from_score(0.9) == "work"
	assert _category_from_score(0.1) == "social"
	assert _category_from_score(0.5) == "work"  # umbral >= 0.5 → work


# --- Fase 4 §3.2: polaroid_stability (estabilidad de refuerzo) ---


def test_polaroid_decay_no_history_is_identity():
	assert polaroid_decay(3.0, None, 1_000_000, tau=90) == 3.0
	assert polaroid_decay(0.0, 1_000_000, 1_000_000 + 86400, tau=90) == 0.0


def test_polaroid_decay_exponential():
	now = 1_800_000_000.0
	last = now - 90 * 86400  # 90 días atrás → e^-1
	decayed = polaroid_decay(1.0, last, now, tau=90)
	assert decayed == pytest.approx(math.exp(-1.0), rel=1e-6)


def test_reinforce_refine_applies_gain_and_stamps(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	f.write_text(REFINE_TEXT, encoding="utf-8")

	reg = FakeRegistry()
	now = 1_800_000_000.0
	result = reinforce_refine(root, reg, f, now=now, tau=90, gain=1.0)

	assert result["reinforced"] is True
	assert result["stability"] == pytest.approx(1.0)
	assert result["ascended"] is False

	fm, _ = parse_refine(f.read_text(encoding="utf-8"))
	assert fm["polaroid_stability"] == pytest.approx(1.0)
	assert fm["last_reinforced_at"] is not None
	assert reg.get("opencode", "opencode:ses_test")["polaroid_stability"] == pytest.approx(1.0)


def test_reinforce_refine_accumulates_over_time(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	f.write_text(REFINE_TEXT, encoding="utf-8")
	reg = FakeRegistry()

	now = 1_800_000_000.0
	r1 = reinforce_refine(root, reg, f, now=now, tau=90, gain=1.0)
	# 7 días después, otro refuerzo: S = 1 * e^(-7/90) + 1 (redondeado a 2 decimales en el sello)
	now += 7 * 86400
	r2 = reinforce_refine(root, reg, f, now=now, tau=90, gain=1.0)
	expected = round(1.0 * math.exp(-7 / 90) + 1.0, 2)
	assert r2["stability"] == pytest.approx(expected, abs=0.005)
	assert r2["stability"] > r1["stability"]


def test_reinforce_refine_ascends_past_gate(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	text = REFINE_TEXT.replace("polaroid_stability: 0.0", "polaroid_stability: 4.5")
	f.write_text(text, encoding="utf-8")

	mm = FakeMemoryManager()
	reg = FakeRegistry()
	result = reinforce_refine(root, reg, f, now=1_800_000_000.0, tau=90, gain=1.0, gate=5.0, memory_manager=mm)
	assert result["reinforced"] is True
	assert result["stability"] == pytest.approx(5.5)  # decay≈0 (acaba de reforzar) + 1
	assert result["ascended"] is True
	assert mm.calls[0]["collection"] == "social_memories"


def test_reinforce_refine_skips_already_ascended(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	text = REFINE_TEXT.replace("ascended: false", "ascended: true")
	f.write_text(text, encoding="utf-8")

	result = reinforce_refine(root, FakeRegistry(), f, now=1_800_000_000.0, tau=90, gain=1.0)
	assert result["reinforced"] is False
	assert result["reason"] == "already_ascended"


def test_refine_frontmatter_declares_polaroid_fields():
	# refine_session declara polaroid_stability/last_reinforced_at con defaults
	# para que reinforce_refine los pueda actualizar in-place (no rompe §4.5.1).
	import inspect

	from red_pill.memento import agentic

	src = inspect.getsource(agentic)
	assert "polaroid_stability" in src
	assert "last_reinforced_at" in src


def test_fase4_config_keys_declared():
	"""Fase 4 §6.7: las claves de config deben estar declaradas en red_pill.config."""
	import red_pill.config as cfg

	assert cfg.POLAROID_TAU == 90.0
	assert cfg.POLAROID_GAIN == 0.5  # ajustado por el experimento (GAIN=1 saturaba)
	assert cfg.POLAROID_REVIVAL_GATE == 7.0  # ajustado por el experimento
	assert cfg.MEMENTO_STATIC_ASCENSION_ENABLED is False  # en sombra hasta calibrar
	assert cfg.MEMENTO_FRAGMENT_OVERLAP_MESSAGES == 2
	assert cfg.MEMENTO_FRAGMENT_MAX_CHARS == 8000  # granite n_ctx 10240 (destilado por fases solapadas)
	assert cfg.MEMENTO_GATE_MIN_SIGNIFICANCE == 0.5
	assert cfg.MEMENTO_CURATED_IMPORTANCE_FACTOR == 5.0  # curados erodan lento
	assert cfg.MEMENTO_CATEGORY_WORK_THRESHOLD == 0.5  # ratio LLM: >= 0.5 → work
	assert cfg.NIGHTLY_ENABLED is True


# --- Fase 4 §4.2: weave_memento_reinforcement (weaver Memento-consciente) ---


class FakeScrollClient:
	def __init__(self, points: list):
		self._points = points

	def collection_exists(self, name):
		return name == "work_memories"

	def scroll(self, **kwargs):
		class Point:
			def __init__(self, payload, i):
				self.payload = payload
				self.id = f"p{i}"

		return [Point(p, i) for i, p in enumerate(self._points)], None


class FakeWeaveMemoryManager(FakeMemoryManager):
	def __init__(self, points, returns=None):
		super().__init__(returns=returns)
		self.client = FakeScrollClient(points)


def test_temas_afines_exact_theme():
	assert _temas_afines("tema_recurrente", set(), {"tema_recurrente", "otra_cosa"}) is True
	assert _temas_afines("tema_recurrente", set(), {"otra_cosa"}) is False


def test_temas_afines_token_overlap():
	refine_tokens = {"memoria", "curaduria", "archivo"}
	engram_topics = {"memoria", "curaduria", "archivo", "otro"}
	assert _temas_afines("", refine_tokens, engram_topics) is True
	engram_topics = {"memoria", "otro", "distinto"}
	assert _temas_afines("", refine_tokens, engram_topics) is False


def test_weave_reinforces_and_ascends(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	text = REFINE_TEXT.replace("polaroid_stability: 0.0", "polaroid_stability: 4.5")
	text = text.replace('texture: {"theme": "memoria_curada"', 'texture: {"theme": "tema_recurrente"')
	f.write_text(text, encoding="utf-8")

	# Un engrama nuevo en work_memories con el mismo tema → refuerza.
	engrama = {"texture": {"theme": "tema_recurrente", "relics": ["la idea vuelve a aparecer"]}, "created_at": 1_800_000_000.0}
	mm = FakeWeaveMemoryManager([engrama])
	reg = FakeRegistry()

	stats = weave_memento_reinforcement(mm, root=root, registry=reg, now=1_800_000_000.0, window_hours=24, tau=90, gain=1.0, gate=5.0)
	assert stats["refine_evaluados"] == 1
	assert stats["refuerzos_aplicados"] == 1
	assert stats["ascensos"] == 1

	fm, _ = parse_refine(f.read_text(encoding="utf-8"))
	assert fm["ascended"] is True
	assert fm["polaroid_stability"] >= 5.0
	# el engrama curado se escribió en social_memories (cuerpo social)
	assert mm.calls[0]["collection"] == "social_memories"


def test_weave_skips_already_ascended(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	f.write_text(REFINE_TEXT.replace("ascended: false", "ascended: true"), encoding="utf-8")

	engrama = {"texture": {"theme": "memoria_curada"}, "created_at": 1_800_000_000.0}
	mm = FakeWeaveMemoryManager([engrama])
	stats = weave_memento_reinforcement(mm, root=root, registry=FakeRegistry(), now=1_800_000_000.0)
	assert stats["refine_evaluados"] == 0  # skipped antes de evaluar
	assert stats["refuerzos_aplicados"] == 0


def test_weave_no_window_returns_early(tmp_path: Path):
	root = tmp_path / "memento"
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True)
	f = d / "001-x.md"
	f.write_text(REFINE_TEXT, encoding="utf-8")
	mm = FakeWeaveMemoryManager([])
	stats = weave_memento_reinforcement(mm, root=root, registry=FakeRegistry(), now=1_800_000_000.0)
	assert stats["refine_evaluados"] == 0
	assert stats["engramas_en_ventana"] == 0


# --- Fase 4 §3.3: ascenso estático por umbral de significance ---


def _write_refine(root: Path, name: str, significance: float, ascended: bool = False) -> Path:
	d = root / "2026-09" / "opencode" / "s" / "refine"
	d.mkdir(parents=True, exist_ok=True)
	f = d / f"{name}.md"
	asc = "true" if ascended else "false"
	f.write_text(
		f"""---
session_id: opencode:{name}
source: opencode
source_lines: memento/index.md#l1-5
significance: {significance}
emotion: gray
intensity: 0.3
texture: {{"theme": "tema_{name}", "relics": []}}
cross_refs: []
ascended: {asc}
ascended_at: null
ascended_to: null
ascended_point_id: null
polaroid_stability: 0.0
last_reinforced_at: null
---
Cuerpo social del refine {name}.
""",
		encoding="utf-8",
	)
	return f


def test_ascend_by_threshold_promotes_above_gate(tmp_path: Path):
	root = tmp_path / "memento"
	_write_refine(root, "alta", 0.8)
	_write_refine(root, "media", 0.5)
	_write_refine(root, "baja", 0.2)

	mm, reg = FakeMemoryManager(), FakeRegistry()
	stats = ascend_by_threshold(root, reg, min_significance=0.5, memory_manager=mm)
	assert stats["ascendidos"] == 2  # 0.8 y 0.5 (>= gate)
	assert stats["rechazados_por_umbral"] == 1  # 0.2
	assert stats["refine_evaluados"] == 3

	ascended = [c for c in mm.calls]
	assert len(ascended) == 2


def test_ascend_by_threshold_skips_ascended(tmp_path: Path):
	root = tmp_path / "memento"
	_write_refine(root, "ya", 0.9, ascended=True)
	mm, reg = FakeMemoryManager(), FakeRegistry()
	stats = ascend_by_threshold(root, reg, min_significance=0.5, memory_manager=mm)
	assert stats["refine_evaluados"] == 0
	assert stats["ascendidos"] == 0


def test_ascend_by_threshold_limit(tmp_path: Path):
	root = tmp_path / "memento"
	for i, sig in enumerate((0.9, 0.8, 0.7)):
		_write_refine(root, f"r{i}", sig)
	mm, reg = FakeMemoryManager(), FakeRegistry()
	stats = ascend_by_threshold(root, reg, min_significance=0.5, memory_manager=mm, limit=2)
	assert stats["ascendidos"] == 2
	assert len(mm.calls) == 2
