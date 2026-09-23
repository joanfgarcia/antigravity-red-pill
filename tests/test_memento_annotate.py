"""Etapa annotate (MEM-006): dedup P1-A, gate de calidad, routing dual y writer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from red_pill.memento.agentic import (
	ANNOTATE_SOCIAL_SYSTEM,
	ANNOTATE_WORK_SYSTEM,
	DUAL_SCORE_SYSTEM,
	annotate_session,
	dedup_annotations,
	quality_flags,
	runtime,
)


def _idea(title, text, sig, theme="t"):
	return {"title": title, "text": text, "significance": sig, "emotion": "cyan", "intensity": 0.6, "theme": theme, "relics": []}


def _fake_transport():
	def transport(system, user, max_tokens):
		if system == ANNOTATE_WORK_SYSTEM:
			return json.dumps(
				[
					_idea("Fix del endpoint", "Joan me pide arreglar el endpoint de auth; le explico el fix y lo despliego.", 0.9, "endpoint"),
					_idea("Ruido", "Hablamos del tiempo y de nada más.", 0.2, "smalltalk"),
				]
			)
		if system == ANNOTATE_SOCIAL_SYSTEM:
			return json.dumps(
				[
					_idea("Fix del endpoint (dup)", "Joan me pide arreglar el endpoint de auth; le explico el fix y lo despliego.", 0.85, "endpoint"),
					_idea("Samantha opina", "Samantha propone una idea sobre el vínculo y el cuidado.", 0.8, "vinculo"),
				]
			)
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
	splits = tmp_path / dir_rel / "memento"
	splits.mkdir(parents=True)
	(splits / "001-split.md").write_text("> [!ref] memento/index.md#l1-20\nJoan me pide arreglar el endpoint.\n", encoding="utf-8")
	return dir_rel


def test_quality_flags_detecta_genero_identidad_voz():
	assert "gender" in quality_flags("Joan me dijo, cansada, que paraba.")
	assert "identity" in quality_flags("Samantha propone una idea.")
	assert "voice" in quality_flags("Aleth ha implementado el protocolo.")
	assert "voice" in quality_flags("Se creó la rama y se generó el PR.")
	assert "voice" in quality_flags("Aleth creó un branch para aislar cambios.")
	assert quality_flags("Joan me pide el fix y le explico el plan.") == []
	assert quality_flags("Creé la rama y generé el PR #37.") == []


def test_extract_tolera_relics_int(monkeypatch):
	from red_pill.memento.agentic import annotate

	def transport(system, user, max_tokens):
		if system == ANNOTATE_WORK_SYSTEM:
			return json.dumps(["texto suelto sin objeto", {"title": "T", "text": "Joan me pide algo.", "significance": 0.9, "relics": 3}])
		return "[]"

	ideas = annotate._extract(transport, "fragmento")
	assert len(ideas) == 1
	assert ideas[0]["relics"] == []


def test_dedup_annotations_colapsa_exactos_y_near_dups():
	items = [
		{"title": "Fix", "text": "Joan me pide arreglar el endpoint de auth y le explico el fix completo.", "significance": 0.9, "flags": []},
		{"title": "Fix dup", "text": "Joan me pide arreglar el endpoint de auth y le explico el fix completo.", "significance": 0.8, "flags": []},
		{"title": "Otra", "text": "Hablamos del tiempo y de nada más.", "significance": 0.2, "flags": []},
	]
	kept = dedup_annotations(items)
	assert len(kept) == 2
	assert kept[0]["significance"] == 0.9


def test_annotate_session_escribe_con_rutas_y_gate(tmp_path, monkeypatch):
	monkeypatch.setattr(runtime, "engine_id", lambda: "test-engine")
	dir_rel = _tree(tmp_path)
	max_sig = annotate_session(tmp_path, dir_rel, "opencode:s1", "opencode", _fake_transport())
	assert max_sig == 0.9
	files = sorted((tmp_path / dir_rel / "annotate").glob("*.md"))
	assert len(files) == 3  # dedup colapsa el gemelo exacto
	by_route = {}
	for f in files:
		txt = f.read_text(encoding="utf-8")
		fm = dict(re.findall(r"^(\w+):\s*(.*)$", txt.split("---")[1], re.M))
		body = txt.split("---", 2)[2].strip()
		by_route[fm["dual_route"]] = (fm, body)
	assert "work" in by_route
	fm, body = by_route["work"]
	assert fm["work_score"] == "0.90"
	assert fm["prompt_version"]
	assert fm["source_lines"]  # obligatorio para el ascenso (regresión 2026-09-23)
	assert "Joan me pide arreglar el endpoint" in body
	assert by_route["none"][0]["quality_flags"] != "[]"  # Samantha → identity → sin ruta
	meta = json.loads((tmp_path / dir_rel / "annotate" / "_meta.json").read_text(encoding="utf-8"))
	assert meta["notas"] == 3
	assert meta["routes"] == {"work": 1, "social": 0, "none": 2}
	assert meta["flags"].get("identity") == 1
	assert meta["annotate_prompt_version"]
	assert meta["annotated_at"]
	assert meta["identity_bio_source"] in ("config", "template") or str(meta["identity_bio_source"]).startswith("override:")
	record = json.loads((tmp_path / dir_rel / "_session.json").read_text(encoding="utf-8"))
	assert record["stages"]["annotate"]["notas"] == 3
	assert record["updated_at"]


class _FakeMM:
	def __init__(self):
		self.calls = []

	def add_memory(self, **kw):
		self.calls.append(kw)
		return kw.get("point_id") or "pid"


class _FakeReg:
	def upsert(self, *a, **k):
		return None


def test_prompt_fingerprints_estables():
	"""Fase 3 RFC-003: mover prompts constante→fichero NO cambia los fingerprints.

	Si cambias un prompt a propósito, actualiza esta tabla (hash mapping) y
	documenta el cambio en el CHANGELOG (los artefactos sellados lo referencian).
	"""
	from red_pill.memento.agentic import (
		annotate_prompt_version,
		distill_prompt_version,
		refine_prompt_version,
		validate_prompt_version,
	)

	assert distill_prompt_version() == "66c679f1bb"
	assert refine_prompt_version() == "85209a6c9e"
	assert annotate_prompt_version() == "07a5c9b529"
	assert validate_prompt_version() == "521a6c19b4"


def test_is_garbage_reason_expoene_la_firma():
	from red_pill.utils.telemetry_filter import is_garbage_reason

	assert is_garbage_reason("hice git commit --amend y luego push") == "ci-signature:git commit"
	assert is_garbage_reason("Joan me pide revisar el endpoint y le explico el plan.") is None


def _note(path, body, extra=""):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		"---\nsession_id: s1\nsource: opencode\nsource_lines: memento/index.md#l10-20\n"
		f"split_ref: memento/index.md#l10-20\nsignificance: 0.9\nemotion: gray\nintensity: 0.5\n"
		f"ascended: false\ndual_route: work\nwork_score: 0.9\nsocial_score: 0.05\n{extra}---\n{body}\n",
		encoding="utf-8",
	)


def test_ascender_sella_rechazo_del_gate_sin_escribir(tmp_path):
	from red_pill.memento.ascension import ascender

	note = tmp_path / "annotate" / "001-git.md"
	_note(note, "Joan me pide hacer git commit con los cambios del endpoint.")
	mm = _FakeMM()
	res = ascender(tmp_path, _FakeReg(), note, memory_manager=mm)
	assert res["ascended"] is False and res["reason"] == "gate_rejected"
	assert mm.calls == []  # no se intentó escribir
	txt = note.read_text(encoding="utf-8")
	assert "validator_approved: false" in txt
	assert "validator: is_garbage" in txt
	assert "machine-noise" in txt


def test_ascender_validadora_usa_bypass_y_sella_engrama(tmp_path):
	from red_pill.memento.ascension import ascender

	note = tmp_path / "annotate" / "002-ok.md"
	_note(note, "Joan me pide hacer git commit con los cambios del endpoint.", extra="validator_approved: true\nvalidator: granite_8b\n")
	mm = _FakeMM()
	res = ascender(tmp_path, _FakeReg(), note, memory_manager=mm)
	assert res["ascended"] is True
	assert mm.calls[0]["content_verified"] is True
	assert mm.calls[0]["metadata"]["content_verified"] is True
	assert mm.calls[0]["metadata"]["ascended_by"] == "validated"


def test_validate_notes_aprueba_y_rechaza(tmp_path, monkeypatch):
	from red_pill.memento.agentic import validate
	from red_pill.memento.agentic.validate import pending_validations, validate_notes

	monkeypatch.setattr(validate.runtime, "engine_id", lambda: "test-engine")
	good = tmp_path / "annotate" / "001-ok.md"
	bad = tmp_path / "annotate" / "002-no.md"
	_note(good, "Joan me pide hacer git commit con los cambios del endpoint.")
	_note(bad, "collected 5 items / 2 errors")

	def transport(system, user, max_tokens):
		return json.dumps(
			[
				{"i": 0, "approved": True, "reason": "narración con comando citado"},
				{"i": 1, "approved": False, "reason": "salida cruda de tests"},
			]
		)

	pend = pending_validations(tmp_path)
	assert len(pend) == 2
	stats = validate_notes(transport, pend)
	assert stats == {"pending": 2, "approved": 1, "rejected": 1, "sin_respuesta": 0}
	txt_good = good.read_text(encoding="utf-8")
	assert "validator_approved: true" in txt_good
	assert "validator: test-engine" in txt_good
	assert "validator_prompt_version:" in txt_good
	assert "validator_approved: false" in bad.read_text(encoding="utf-8")
	assert pending_validations(tmp_path) == []


def test_ascender_acepta_anotacion_con_source_lines(tmp_path):
	"""Regresión (incidente 2026-09-23): las notas annotate deben escribir
	`source_lines` (= split_ref); sin él `ascender` devolvía missing_key y el
	borrado legacy dejaba las sesiones sin engramas."""
	from red_pill.memento.ascension import ascender

	note = tmp_path / "annotate" / "002-filtro-de-empatia.md"
	note.parent.mkdir(parents=True)
	note.write_text(
		"---\nsession_id: s1\nsource: opencode\nsource_lines: memento/index.md#l10-20\n"
		"split_ref: memento/index.md#l10-20\nsignificance: 0.9\nemotion: gray\nintensity: 0.5\n"
		"ascended: false\ndual_route: work\nwork_score: 0.9\nsocial_score: 0.05\n---\nJoan me pide el fix y le explico.\n",
		encoding="utf-8",
	)
	mm = _FakeMM()
	res = ascender(tmp_path, _FakeReg(), note, memory_manager=mm)
	assert res["ascended"] is True
	assert res["collection"] == "work_memories"
	assert mm.calls[0]["metadata"]["dual_route"] == "work"
	assert mm.calls[0]["metadata"]["source_lines"] == "memento/index.md#l10-20"


def test_session_record_fusiona_etapas(tmp_path):
	from red_pill.memento.record import bump_session_record, read_session_record, update_session_record

	dir_rel = "2026-09/opencode/s1"
	(tmp_path / dir_rel).mkdir(parents=True)
	update_session_record(tmp_path, dir_rel, "distill", {"sections": 2})
	update_session_record(tmp_path, dir_rel, "annotate", {"notas": 5})
	bump_session_record(tmp_path, dir_rel, "ascend", {"ascendidos": 3})
	bump_session_record(tmp_path, dir_rel, "ascend", {"ascendidos": 2})
	record = read_session_record(tmp_path, dir_rel)
	assert record["stages"]["distill"]["sections"] == 2
	assert record["stages"]["annotate"]["notas"] == 5
	assert record["stages"]["ascend"]["ascendidos"] == 5
	assert record["updated_at"]


def test_score_dual_reintenta_faltantes(monkeypatch):
	from red_pill.memento.agentic import annotate

	anns = [{"text": f"nota {i}"} for i in range(4)]
	calls = {"n": 0}

	def transport(system, user, max_tokens):
		calls["n"] += 1
		if calls["n"] == 1:
			return json.dumps([{"i": 0, "work_score": 0.9, "social_score": 0.1}])
		pending_n = sum(1 for a in anns if "work_score" not in a)
		return json.dumps([{"i": i, "work_score": 0.8, "social_score": 0.1} for i in range(pending_n)])

	annotate._score_dual(transport, anns)
	assert all("work_score" in a for a in anns)
	assert calls["n"] == 2


def test_rewrite_voice_notes_reescribe_no_primera_persona(monkeypatch):
	from red_pill.memento.agentic import annotate

	anns = [
		{"text": "Se creó la rama y se generó el PR.", "flags": ["voice"]},
		{"text": "Joan me pide el fix y le explico el plan.", "flags": []},
	]
	calls = {"n": 0}

	def transport(system, user, max_tokens):
		calls["n"] += 1
		return json.dumps([{"i": 0, "text": "Creé la rama y generé el PR #37."}])

	rewritten = annotate.rewrite_voice_notes(transport, anns)
	assert rewritten == 1
	assert anns[0]["text"].startswith("Creé la rama")
	assert calls["n"] == 1


def test_rewrite_voice_notes_reintenta_hasta_cubrir(monkeypatch):
	from red_pill.memento.agentic import annotate

	anns = [{"text": f"Se implementó la tarea {i} en el sistema.", "flags": []} for i in range(3)]

	def transport(system, user, max_tokens):
		idx = [int(m) for m in re.findall(r"^\[(\d+)\]", user, re.M)]
		if len(idx) > 1:
			idx = idx[:-1]
		return json.dumps([{"i": i, "text": f"Implementé la tarea {i} en el sistema."} for i in idx])

	rewritten = annotate.rewrite_voice_notes(transport, anns)
	assert all(annotate.is_first_person(a["text"]) for a in anns)
	assert rewritten == 3


def test_is_first_person():
	from red_pill.memento.agentic import is_first_person

	assert is_first_person("Joan me pide algo y le explico.")
	assert is_first_person("Creé la rama y generé el PR.")
	assert not is_first_person("Se creó la rama y se generó el PR.")


def test_identity_bio_precedencia_env(tmp_path, monkeypatch):
	from red_pill.memento.agentic import prompts

	bio = tmp_path / "bio.md"
	bio.write_text("BIO DE PRUEBA", encoding="utf-8")
	monkeypatch.setenv("RP_IDENTITY_BIO", str(bio))
	assert prompts._load_identity_bio() == "BIO DE PRUEBA"
	assert prompts._identity_bio_with_source()[1].startswith("override:")
	monkeypatch.delenv("RP_IDENTITY_BIO")
	# Sin override: config del operador o plantilla neutra (nunca vacío).
	assert prompts._identity_bio_with_source()[1] in ("config", "template")
	assert "IDENTIDAD" in prompts._load_identity_bio()


def test_candidate_category_prefiere_dual_route():
	from red_pill.memento.ascension import _candidate_category

	assert _candidate_category({"dual_route": "work"}, "contenido personal y emocional") == "work"
	assert _candidate_category({"dual_route": "social"}, "código y tests") == "social"


def test_ascender_dual_route_none_no_asciende(tmp_path):
	from red_pill.memento.ascension import ascender

	refine = tmp_path / "refine" / "001-x.md"
	refine.parent.mkdir(parents=True)
	refine.write_text(
		"---\nsession_id: s1\nsource: opencode\nsource_lines: memento/index.md#l1-10\n"
		"significance: 0.9\nemotion: gray\nintensity: 0.5\nascended: false\ndual_route: none\n---\nNota sin ruta.\n",
		encoding="utf-8",
	)
	res = ascender(tmp_path, None, refine)
	assert res == {"ascended": False, "reason": "dual_route_none"}
