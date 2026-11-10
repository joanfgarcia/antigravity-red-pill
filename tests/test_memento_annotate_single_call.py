"""NB-001 F4 (P7): fusión work+social en UNA llamada con `scope` por idea.

Contrato (PLAN-NB-001 §3 F4 / D-NB-04/06):
- Flag `MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED` (RULE 4, default OFF). OFF → dos
  llamadas por split (work + social), comportamiento actual exacto.
- ON → una llamada combinada (`annotate_combined_user[_v2|_v3]`) que devuelve un
  ARRAY con `scope` ("work" | "social") por idea.
- El `scope` se persiste en la idea, el parcial y el frontmatter; el routing
  (`_route` sobre los scores duales) NO cambia.
- La firma de la etapa cambia solo con el flag ON (marca `annotate_extract=single`).
"""

from __future__ import annotations

import json

import pytest

import red_pill.config as cfg
from red_pill.memento.agentic import (
	ANNOTATE_COMBINED_SYSTEM,
	ANNOTATE_WORK_SYSTEM,
	DUAL_SCORE_SYSTEM,
	annotate_session,
)
from red_pill.memento.agentic import runtime as agentic_runtime


@pytest.fixture(autouse=True)
def _pin_runtime(monkeypatch):
	monkeypatch.setattr(agentic_runtime, "engine_id", lambda: "granite-test")
	monkeypatch.setattr(agentic_runtime, "model_trust", lambda: "full")
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_REWRITE", False)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_POST_REWRITE_DEDUP", False)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED", False)


def _single_call_on(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_SINGLE_CALL_ENABLED", True)


def test_flag_default_off_and_combined_id_none():
	assert agentic_runtime.single_call_enabled() is False
	assert agentic_runtime.annotate_combined_prompt_id() is None


def test_flag_on_resolves_combined_prompt_id(monkeypatch):
	_single_call_on(monkeypatch)
	assert agentic_runtime.single_call_enabled() is True
	# La variante sigue a annotate_prompt_set(); sin override del perfil → la que
	# corresponda al config del puesto (v1/v2/v3). Basta con que sea un id combinado.
	assert agentic_runtime.annotate_combined_prompt_id() in (
		"annotate_combined_user",
		"annotate_combined_user_v2",
		"annotate_combined_user_v3",
	)


def test_extract_single_call_one_call_with_scope(monkeypatch):
	"""ON → una sola llamada combinada; cada idea conserva su `scope`."""
	from red_pill.memento.agentic import annotate

	_single_call_on(monkeypatch)
	monkeypatch.setattr(agentic_runtime, "annotate_prompt_set", lambda: "")
	calls = []

	def transport(system, user, max_tokens):
		calls.append(system)
		if system == ANNOTATE_COMBINED_SYSTEM:
			return json.dumps(
				[
					{"scope": "work", "title": "W", "text": "Joan me pide arreglar el endpoint.", "significance": 0.9, "relics": []},
					{"scope": "social", "title": "S", "text": "Hablamos del vínculo y el cuidado.", "significance": 0.8, "relics": []},
					{"scope": "rare", "title": "X", "text": "Un scope no válido se descarta.", "significance": 0.5, "relics": []},
				]
			)
		return "[]"

	ideas = annotate._extract(transport, "fragmento")
	assert len(calls) == 1, "la fusión debe emitir UNA llamada por split"
	assert [i.get("scope") for i in ideas] == ["work", "social", None]


def test_extract_two_calls_baseline_when_flag_off(monkeypatch):
	"""OFF → dos llamadas (work + social) y SIN `scope` (comportamiento actual)."""
	from red_pill.memento.agentic import annotate

	monkeypatch.setattr(agentic_runtime, "annotate_prompt_set", lambda: "")
	calls = []

	def transport(system, user, max_tokens):
		calls.append(system)
		if system == ANNOTATE_WORK_SYSTEM:
			return json.dumps([{"title": "W", "text": "Joan me pide arreglar el endpoint.", "significance": 0.9, "relics": []}])
		return "[]"

	ideas = annotate._extract(transport, "fragmento")
	assert len(calls) == 2
	assert ideas and "scope" not in ideas[0]


def test_annotate_session_persists_scope_in_frontmatter(tmp_path, monkeypatch):
	"""ON → el `scope` se sella en el frontmatter de la nota materializada."""
	from red_pill.memento.ascension import parse_refine

	_single_call_on(monkeypatch)
	monkeypatch.setattr(agentic_runtime, "annotate_prompt_set", lambda: "")

	def transport(system, user, max_tokens):
		if system == ANNOTATE_COMBINED_SYSTEM:
			return json.dumps(
				[
					{"scope": "work", "title": "Fix endpoint", "text": "Joan me pide arreglar el endpoint y lo despliego.", "significance": 0.9, "emotion": "blue", "intensity": 0.6, "theme": "endpoint", "relics": []},
					{"scope": "social", "title": "El vínculo", "text": "Hablamos del vínculo y el cuidado.", "significance": 0.8, "emotion": "orange", "intensity": 0.5, "theme": "vinculo", "relics": []},
				]
			)
		if system == DUAL_SCORE_SYSTEM:
			return json.dumps(
				[
					{"i": 0, "work_score": 0.9, "social_score": 0.1},
					{"i": 1, "work_score": 0.2, "social_score": 0.8},
				]
			)
		return "[]"

	dir_rel = "2026-09/opencode/s1"
	(tmp_path / dir_rel / "memento").mkdir(parents=True)
	(tmp_path / dir_rel / "memento" / "001-split.md").write_text(
		"> [!ref] memento/index.md#l1-20\nJoan me pide arreglar el endpoint.\n", encoding="utf-8"
	)
	annotate_session(tmp_path, dir_rel, "opencode:s1", "opencode", transport)

	annotate_dir = tmp_path / dir_rel / "annotate"
	scopes = {}
	for note in sorted(annotate_dir.glob("*.md")):
		fm, _ = parse_refine(note.read_text(encoding="utf-8"))
		scopes[fm["title"]] = fm.get("scope")
	assert scopes == {"Fix endpoint": "work", "El vínculo": "social"}


def test_scope_roundtrips_through_from_notes(tmp_path, monkeypatch):
	"""El `scope` sellado se reconstruye desde las notas (`--from`), sin el flag."""
	from red_pill.memento.agentic.annotation_state import _annotations_from_notes, _contract

	_single_call_on(monkeypatch)
	monkeypatch.setattr(agentic_runtime, "annotate_prompt_set", lambda: "")

	def transport(system, user, max_tokens):
		if system == ANNOTATE_COMBINED_SYSTEM:
			return json.dumps([{"scope": "work", "title": "Fix", "text": "Joan me pide arreglar el endpoint.", "significance": 0.9, "relics": []}])
		if system == DUAL_SCORE_SYSTEM:
			return json.dumps([{"i": 0, "work_score": 0.9, "social_score": 0.1}])
		return "[]"

	dir_rel = "2026-09/opencode/s1"
	(tmp_path / dir_rel / "memento").mkdir(parents=True)
	(tmp_path / dir_rel / "memento" / "001-split.md").write_text(
		"> [!ref] memento/index.md#l1-20\nJoan me pide arreglar el endpoint.\n", encoding="utf-8"
	)
	annotate_session(tmp_path, dir_rel, "opencode:s1", "opencode", transport)

	annotate_dir = tmp_path / dir_rel / "annotate"
	ideas = _annotations_from_notes(annotate_dir, _contract(False))
	assert ideas is not None and len(ideas) == 1
	assert ideas[0]["scope"] == "work"


def test_signature_differs_when_flag_on(monkeypatch):
	"""La firma de la etapa cambia con el flag ON (y no con OFF)."""
	from red_pill.memento.agentic import prompts, runtime

	monkeypatch.setattr(prompts, "IDENTITY_BIO", "TEST-BIO-FIXED")
	monkeypatch.setattr(runtime, "fragment_view_settings", lambda: ("raw", "op", "ag"))
	monkeypatch.setattr(runtime, "annotate_prompt_set", lambda: "")
	monkeypatch.setattr(runtime, "voice_v2_enabled", lambda: False)
	monkeypatch.setattr(cfg, "MEMENTO_PROMPT_LANGUAGE", "auto")

	off = runtime.annotate_prompt_version()
	_single_call_on(monkeypatch)
	on = runtime.annotate_prompt_version()
	assert off != on
