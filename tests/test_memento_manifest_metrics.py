"""MEM-010 F1: manifest estructurado + métricas por sesión + input_hash.

Aislamiento (regla del operador): estos tests NO tocan servicios vivos — todo
corre sobre `tmp_path`, el transporte LLM es falso y no se importa Qdrant ni
sqlite. Las guardas autouse de `tests/conftest.py` (REDPILL_TESTING,
bunker_isolation) siguen activas por si acaso.
"""

from __future__ import annotations

import json
from pathlib import Path

from red_pill.memento.agentic import (
	ANNOTATE_SOCIAL_SYSTEM,
	ANNOTATE_WORK_SYSTEM,
	DUAL_SCORE_SYSTEM,
	annotate_session,
	runtime,
)
from red_pill.memento.agentic.annotate import compute_note_metrics, session_input_hash
from red_pill.memento.render import compute_hash, extract_body


def _idea(title, text, sig, theme="t"):
	return {"title": title, "text": text, "significance": sig, "emotion": "cyan", "intensity": 0.6, "theme": theme, "relics": []}


def _fake_transport():
	def transport(system, user, max_tokens):
		if system == ANNOTATE_WORK_SYSTEM:
			return json.dumps(
				[
					_idea("Fix endpoint", "Joan me pide arreglar el endpoint de auth; le explico el plan y lo despliego.", 0.9, "endpoint"),
					_idea("Ruido", "Hablamos del tiempo y de nada más.", 0.2, "smalltalk"),
				]
			)
		if system == ANNOTATE_SOCIAL_SYSTEM:
			return json.dumps([_idea("Vinculo", "Joan me cuenta cómo se siente y le respondo con calma.", 0.8, "vinculo")])
		if system == DUAL_SCORE_SYSTEM:
			return json.dumps(
				[
					{"i": 0, "work_score": 0.9, "social_score": 0.1},
					{"i": 1, "work_score": 0.3, "social_score": 0.7},
					{"i": 2, "work_score": 0.2, "social_score": 0.2},
				]
			)
		return "[]"

	return transport


def _tree(tmp_path: Path) -> str:
	dir_rel = "2026-09/opencode/s1"
	session = tmp_path / dir_rel / "memento"
	session.mkdir(parents=True)
	index = "# sess\n\nJoan me pide arreglar el endpoint.\n"
	(session / "index.md").write_text(index, encoding="utf-8")
	(session / "001-split.md").write_text("> [!ref] memento/index.md#l1-20\nJoan me pide arreglar el endpoint.\n", encoding="utf-8")
	return dir_rel


# ── manifest ─────────────────────────────────────────────────────────────────


def test_manifest_determinista_y_contratos_separados():
	m1 = runtime.annotate_manifest()
	m2 = runtime.annotate_manifest()
	assert m1 == m2
	assert m1["schema"] == runtime.MANIFEST_SCHEMA == "gate-manifest-v1"
	assert m1["extract_contract"] and m1["score_contract"]
	assert m1["extract_contract"] != m1["score_contract"]
	assert runtime.annotate_manifest_hash() == runtime.annotate_manifest_hash()
	components = m1["components"]
	for key in ("extract_work", "extract_social", "voice_rewrite_prompt", "dual_score", "bio", "work_scope", "social_scope", "fragment_view", "dedup_policy", "thresholds"):
		assert key in components, key
	assert components["dedup_policy"]["threshold"] == runtime.memento_dedup_threshold()


def test_manifest_reacciona_por_contrato(monkeypatch):
	import red_pill.config as cfg

	base = runtime.annotate_manifest()
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_DEAD_ZONE", 0.99, raising=False)
	scored = runtime.annotate_manifest()
	assert scored["score_contract"] != base["score_contract"]
	assert scored["extract_contract"] == base["extract_contract"]

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FRAGMENT_VIEW", "pairs", raising=False)
	viewed = runtime.annotate_manifest()
	assert viewed["extract_contract"] != scored["extract_contract"]
	assert viewed["score_contract"] == scored["score_contract"]


def test_manifest_no_altera_el_fingerprint_legacy():
	before = runtime.annotate_prompt_version()
	runtime.annotate_manifest()
	assert runtime.annotate_prompt_version() == before
	assert before.startswith("p1:")


# ── métricas ─────────────────────────────────────────────────────────────────


def test_compute_note_metrics_basico():
	long_a = "Joan me pide refactorizar el modulo de colas y le explico el diseno completo del cambio. " * 8
	long_b = "Creo la rama con el arreglo del semaforo y valido la suite entera antes del merge. " * 8
	annotations = [
		{"title": "A", "text": long_a, "work_score": 0.9, "social_score": 0.1},
		{"title": "B", "text": long_b, "work_score": 0.7, "social_score": 0.5},
		{"title": "C", "text": "La narradora del Bunker relata que Aleth propuso el cambio.", "work_score": 0.6, "social_score": 0.6},
	]
	metrics = compute_note_metrics(annotations, dedup_threshold=0.6)
	assert metrics["notas"] == 3
	assert metrics["pct_gt_600"] == round(100 * 2 / 3, 1)
	assert metrics["dedup_threshold"] == 0.6
	assert metrics["min_margin"] == 0.0
	assert metrics["bio_leaks"] == 1
	assert metrics["near_dups"] == 0
	assert 0.0 <= metrics["pct_primera_persona"] <= 100.0


def test_near_dups_usa_el_umbral_efectivo():
	# solape = 5 tokens comunes / min(7, 8) = 0.625 → par con umbral 0.6, no con 0.8
	a = {"title": "x", "text": "alpha bravo charlie delta eco foxtrot gato", "work_score": 0.5, "social_score": 0.1}
	b = {"title": "y", "text": "alpha bravo charlie delta eco hotel india julio", "work_score": 0.5, "social_score": 0.1}
	assert compute_note_metrics([a, b], dedup_threshold=0.6)["near_dups"] == 1
	assert compute_note_metrics([a, b], dedup_threshold=0.8)["near_dups"] == 0


def test_metrics_min_margin_y_none_sin_puntuaciones():
	annotations = [{"title": "A", "text": "Joan me pide algo concreto.", "work_score": 0.8, "social_score": 0.3}]
	metrics = compute_note_metrics(annotations, dedup_threshold=0.6)
	assert metrics["min_margin"] == 0.5
	sin = compute_note_metrics([{"title": "A", "text": "Joan me pide algo concreto."}], dedup_threshold=0.6)
	assert sin["min_margin"] is None


# ── integración annotate (sandbox: tmp_path + transporte falso) ──────────────


def test_annotate_meta_lleva_manifest_metrics_e_input_hash(tmp_path, monkeypatch):
	monkeypatch.setattr(runtime, "engine_id", lambda: "test-engine")
	dir_rel = _tree(tmp_path)
	annotate_session(tmp_path, dir_rel, "opencode:s1", "opencode", _fake_transport())
	meta = json.loads((tmp_path / dir_rel / "annotate" / "_meta.json").read_text(encoding="utf-8"))
	assert meta["manifest"]["schema"] == "gate-manifest-v1"
	assert meta["manifest_hash"] == runtime.annotate_manifest_hash()
	assert meta["metrics"]["notas"] == meta["notas"]
	assert meta["metrics"]["dedup_threshold"] == runtime.memento_dedup_threshold()
	index_text = (tmp_path / dir_rel / "memento" / "index.md").read_text(encoding="utf-8")
	assert meta["input_hash"] == compute_hash(extract_body(index_text))
	assert meta["input_hash_source"] == "index"
	# El espejo por sesión lleva los mismos campos.
	record = json.loads((tmp_path / dir_rel / "_session.json").read_text(encoding="utf-8"))
	assert record["stages"]["annotate"]["manifest_hash"] == meta["manifest_hash"]
	assert record["stages"]["annotate"]["metrics"]["notas"] == meta["notas"]


def test_session_input_hash_fallback_sin_index(tmp_path):
	dir_rel = "2026-09/opencode/s2"
	session = tmp_path / dir_rel / "memento"
	session.mkdir(parents=True)
	(session / "001-split.md").write_text("> [!ref] memento/index.md#l1-9\nJoan me pide algo.\n", encoding="utf-8")
	from red_pill.memento.agentic.fragments import work_units

	units = work_units(tmp_path / dir_rel)
	h1, source = session_input_hash(tmp_path, dir_rel, units)
	h2, _ = session_input_hash(tmp_path, dir_rel, units)
	assert source == "units"
	assert h1 and h1 == h2
