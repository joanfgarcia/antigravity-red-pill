"""AD-146: annotate trocea el split en partes de tamaño SIMILAR (≤ max_chars).

Contexto: las unidades de annotate son los splits de `memento/` (p50 12,2k chars,
p90 14,3k, p99 24,1k). Con K2 a 10.240, el p99 no cabe (falla con
`PromptTooLongError`) y a 16.384 la generación completa supera el watchdog de
180 s. El pase trocea en trozos balanceados (ceil(chars/tope)), no 8.000 + 1.000.
"""

from __future__ import annotations

import json

import pytest

import red_pill.config as cfg
from red_pill.memento.agentic import (
	ANNOTATE_SOCIAL_SYSTEM,
	ANNOTATE_WORK_SYSTEM,
	DUAL_SCORE_SYSTEM,
	annotate_session,
	fragments,
)
from red_pill.memento.agentic import runtime as agentic_runtime
from red_pill.memento.agentic.annotation_state import _annotations_from_notes, _contract


@pytest.fixture(autouse=True)
def _pin_runtime(monkeypatch):
	monkeypatch.setattr(agentic_runtime, "engine_id", lambda: "k2-test")
	monkeypatch.setattr(agentic_runtime, "model_trust", lambda: "full")
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", True)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_REWRITE", False)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_POST_REWRITE_DEDUP", False)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED", False)
	monkeypatch.setattr(cfg, "MEMENTO_STATIC_ASCENSION_ENABLED", False)


def test_balanced_chunks_reparte_sin_residual():
	text = "".join(f"## 2026-09-0{i}T00:00:00Z — Usuario\npalabra {'x' * 40}\n" for i in range(1, 7))
	for max_chars in (200, 400, 1000):
		chunks = fragments.balanced_chunks(text, max_chars)
		assert "".join(chunks) == text, "no puede perder ni duplicar texto"
		assert all(0 < len(c) <= max_chars for c in chunks)
		assert len(chunks) == -(-len(text) // max_chars)
		target = len(text) / len(chunks)
		# Balance: ningún trozo se aleja más del 25% del tamaño medio.
		assert all(abs(len(c) - target) <= max(target * 0.25, 40) for c in chunks), [len(c) for c in chunks]


def test_balanced_chunks_sin_cortes_semanticos_no_parte_palabras():
	text = "palabra " * 500
	chunks = fragments.balanced_chunks(text, 1000)
	assert "".join(chunks) == text
	assert all(len(c) <= 1000 and not c.startswith("abra ") for c in chunks)


def test_balanced_chunks_desactivado_devuelve_entero():
	assert fragments.balanced_chunks("abc", 0) == ["abc"]
	assert fragments.balanced_chunks("abc", 10) == ["abc"]


def test_annotate_extrae_una_vez_por_trozo(tmp_path, monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_CHUNK_CHARS", 300)
	dir_rel = "2026-09/opencode/s1"
	memento = tmp_path / dir_rel / "memento"
	memento.mkdir(parents=True)
	body = "".join(
		f"## 2026-09-0{i}T00:00:00Z — Usuario\nJoan me pide medir el contexto del modelo número {i}. " + "texto " * 25 + "\n"
		for i in range(1, 7)
	)
	(memento / "001-split.md").write_text(f"> [!ref] memento/index.md#l1-20\n{body}", encoding="utf-8")

	work_calls = []
	# Frases con vocabulario casi disjunto: el dedup P1-A (contención de tokens)
	# fundiría textos que sólo cambien en un número.
	frases = [
		"Joan me pide medir la latencia del servidor con precisión quirúrgica.",
		"Hablamos del presupuesto mensual y los gastos imprevistos del hogar.",
		"Revisamos la arquitectura del búnker y el aislamiento térmico del sótano.",
		"Comentamos una película danesa: fotografía fría, silencios largos, final ambiguo.",
		"Discutimos el calendario lunar y su influencia en las mareas del puerto.",
		"Planeamos sembrar tomates, albahaca y romero en la terraza norte.",
	]

	def transport(system, user, max_tokens):
		if system == ANNOTATE_WORK_SYSTEM:
			work_calls.append(len(user))
			n = len(work_calls)
			return json.dumps([{"title": f"t{n}", "text": frases[(n - 1) % len(frases)], "significance": 0.9, "relics": []}])
		if system == ANNOTATE_SOCIAL_SYSTEM:
			return "[]"
		if system == DUAL_SCORE_SYSTEM:
			return json.dumps([{"i": i, "work_score": 0.9, "social_score": 0.1} for i in range(len(work_calls))])
		return "[]"

	annotate_session(tmp_path, dir_rel, "opencode:s1", "opencode", transport)

	chunks = fragments.balanced_chunks(body, 300)
	assert len(work_calls) == len(chunks), f"{len(work_calls)} llamadas para {len(chunks)} trozos"
	ideas = _annotations_from_notes(tmp_path / dir_rel / "annotate", _contract(False))
	assert ideas is not None and len(ideas) == len(chunks)
