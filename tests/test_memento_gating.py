"""MEM-010 F2: gating previo — registro `stages.gate`, fast-path y predicados.

Aislamiento: solo `tmp_path` + ficheros; sin Qdrant/sqlite/servicios (las guardas
autouse de conftest siguen activas). La concurrencia se prueba con hilos sobre
el mismo fichero (flock real, fds distintos).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from red_pill.memento import gating
from red_pill.memento.record import bump_session_record, read_session_record, update_session_record

# ── helpers ──────────────────────────────────────────────────────────────────


def _meta(manifest=None, **over):
	pipeline = gating.current_pipeline()
	base = {
		"engine": "test-engine",
		"annotate_prompt_version": pipeline["legacy_fingerprint"],
		"manifest": manifest if manifest is not None else pipeline["manifest"],
		"metrics": {"pct_primera_persona": 100.0, "min_margin": 0.5, "bio_leaks": 0, "near_dups": 0, "dedup_threshold": 0.6},
		"flags": {},
		"routes": {"work": 1, "social": 0, "none": 0},
		"notas": 1,
	}
	base.update(over)
	return base


def _session(tmp_path: Path, name="s1", *, meta=None, partial=False, notes=None) -> str:
	dir_rel = f"2026-09/opencode/{name}"
	session = tmp_path / dir_rel
	(session / "memento").mkdir(parents=True)
	(session / "memento" / "index.md").write_text("# s\n\nJoan me pide algo.\n", encoding="utf-8")
	(session / "annotate").mkdir(exist_ok=True)
	if meta is not None:
		(session / "annotate" / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
	if partial:
		(session / "annotate" / "_partial.json").write_text("{}", encoding="utf-8")
	for i, text in enumerate(notes or []):
		(session / "annotate" / f"00{i}-n.md").write_text(f"---\ntitle: t{i}\n---\n{text}\n", encoding="utf-8")
	return dir_rel


def _tweaked_manifest(component: str, value):
	manifest = json.loads(json.dumps(gating.current_pipeline()["manifest"]))
	manifest["components"][component] = value
	return manifest


# ── record: concurrencia ─────────────────────────────────────────────────────


def test_record_concurrencia_sin_perdidas(tmp_path):
	dir_rel = "2026-09/opencode/race"

	def bumper():
		for _ in range(20):
			bump_session_record(tmp_path, dir_rel, "ascend", {"ascendidos": 1})

	def writer(i):
		update_session_record(tmp_path, dir_rel, f"stage{i}", {"v": i})

	with ThreadPoolExecutor(max_workers=12) as ex:
		futures = [ex.submit(bumper) for _ in range(8)] + [ex.submit(writer, i) for i in range(4)]
		for fut in futures:
			fut.result(timeout=30)
	record = read_session_record(tmp_path, dir_rel)
	assert record["stages"]["ascend"]["ascendidos"] == 160
	for i in range(4):
		assert record["stages"][f"stage{i}"]["v"] == i


# ── sellado: upsert + cap ────────────────────────────────────────────────────


def test_seal_upsert_por_run_id_y_cap(tmp_path):
	dir_rel = _session(tmp_path)
	pipeline = gating.current_pipeline()
	for i in range(3):
		gating.seal(
			tmp_path, dir_rel, run_id="r1", action="skip", state="skipped",
			reason=f"v{i}", to_fingerprint=pipeline["manifest_hash"],
		)
	gate = gating.read_gate(tmp_path, dir_rel)
	assert len(gate["history"]) == 1  # upsert: no duplica el mismo run
	assert gate["latest"]["reason"] == "v2"
	for i in range(12):
		gating.seal(
			tmp_path, dir_rel, run_id=f"r{i}", action="skip", state="skipped",
			reason="x", to_fingerprint=pipeline["manifest_hash"],
		)
	gate = gating.read_gate(tmp_path, dir_rel)
	assert len(gate["history"]) == gating.HISTORY_CAP
	assert gate["history"][-1]["run_id"] == "r11"


# ── fast-path / parcial / failed ─────────────────────────────────────────────


def test_gate_session_skip_sellado_e_idempotente(tmp_path):
	dir_rel = _session(tmp_path, meta=_meta())
	pipeline = gating.current_pipeline()
	first = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=pipeline)
	assert first["action"] == "skip" and first["state"] == "skipped" and first["emit"] is False
	record = tmp_path / dir_rel / "_session.json"
	before = record.read_text(encoding="utf-8")
	second = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=pipeline)
	assert second["fast_path"] is True
	assert record.read_text(encoding="utf-8") == before  # sin re-sellado


def test_partial_manda_resume_partial(tmp_path):
	dir_rel = _session(tmp_path, meta=_meta(), partial=True)
	result = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=gating.current_pipeline())
	assert result["action"] == "process"
	assert result["state"] == "pending"
	assert result["reason"] == "resume-partial"
	assert result["emit"] is True


def test_failed_terminal_no_reintenta(tmp_path):
	dir_rel = _session(tmp_path, meta=_meta())
	pipeline = gating.current_pipeline()
	gating.seal(
		tmp_path, dir_rel, run_id="r1", action="process", state="failed",
		reason="fallo inyectado", to_fingerprint=pipeline["manifest_hash"],
		input_hash=gating.session_input_hash(tmp_path, dir_rel),
	)
	result = gating.gate_session(tmp_path, dir_rel, run_id="r2", pipeline=pipeline)
	assert result["fast_path"] is True
	assert result["emit"] is False


def test_engine_distinto_procesa(tmp_path):
	dir_rel = _session(tmp_path, meta=_meta())
	result = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=gating.current_pipeline(), engine="otro_motor")
	assert result["action"] == "process"
	assert "engine" in result["reason"]


# ── deltas y predicados ──────────────────────────────────────────────────────


def test_manifest_delta():
	pipeline = gating.current_pipeline()
	new = pipeline["manifest"]
	assert gating.manifest_delta(new, new) == []
	changed = _tweaked_manifest("bio", "sha256:otro")
	assert gating.manifest_delta(changed, new) == ["bio"]
	assert gating.manifest_delta(None, new) is None
	assert gating.manifest_delta({"schema": "otro"}, new) == ["schema"]


def test_predicados_condicionales(tmp_path):
	pipeline = gating.current_pipeline()
	annotate_dir = tmp_path / "annotate"
	annotate_dir.mkdir()

	# voz con defecto → process; sin defecto → skip
	action, _ = gating.predicate_action(["voice_rewrite_prompt"], {"flags": {"voice": 2}}, {"pct_primera_persona": 90.0}, annotate_dir, pipeline)
	assert action == "process"
	action, _ = gating.predicate_action(["voice_rewrite_prompt"], {"flags": {}}, {"pct_primera_persona": 100.0}, annotate_dir, pipeline)
	assert action == "skip"

	# bio con leak → process; limpia → skip
	action, _ = gating.predicate_action(["bio"], {"flags": {}}, {"bio_leaks": 1}, annotate_dir, pipeline)
	assert action == "process"
	action, _ = gating.predicate_action(["bio"], {"flags": {}}, {"bio_leaks": 0}, annotate_dir, pipeline)
	assert action == "skip"

	# scopes: notas en zona muerta → process
	action, _ = gating.predicate_action(["work_scope"], {"routes": {"none": 2}}, {"min_margin": 0.5}, annotate_dir, pipeline)
	assert action == "process"
	action, _ = gating.predicate_action(["work_scope"], {"routes": {"none": 0}}, {"min_margin": 0.5}, annotate_dir, pipeline)
	assert action == "skip"

	# dedup: sin notas → skip; con near-dups residuales → process
	action, _ = gating.predicate_action(["dedup_policy"], {"flags": {}}, {}, annotate_dir, pipeline)
	assert action == "skip"
	common = "alpha bravo charlie delta eco foxtrot gato"
	near = "alpha bravo charlie delta eco hotel india julio"
	(annotate_dir / "001-a.md").write_text(f"---\ntitle: a\n---\n{common}\n", encoding="utf-8")
	(annotate_dir / "002-b.md").write_text(f"---\ntitle: b\n---\n{near}\n", encoding="utf-8")
	action, _ = gating.predicate_action(["dedup_policy"], {"flags": {}}, {}, annotate_dir, pipeline)
	assert action == "process"

	# scorer → rescore; extract → process
	action, _ = gating.predicate_action(["dual_score"], {}, {}, annotate_dir, pipeline)
	assert action == "rescore"
	action, _ = gating.predicate_action(["extract_work"], {}, {}, annotate_dir, pipeline)
	assert action == "process"


def test_gate_session_procesa_con_delta_de_voz(tmp_path):
	meta = _meta(
		manifest=_tweaked_manifest("voice_rewrite_prompt", "p1:viejo"),
		flags={"voice": 3},
	)
	dir_rel = _session(tmp_path, meta=meta)
	result = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=gating.current_pipeline())
	assert result["action"] == "process" and result["emit"] is True
	gate = gating.read_gate(tmp_path, dir_rel)
	assert gate["latest"]["delta"] == ["voice_rewrite_prompt"]
	assert gate["latest"]["from_fingerprint"] == meta["annotate_prompt_version"]


def test_legacy_sin_manifest_misma_version_salta(tmp_path):
	meta = _meta()
	meta.pop("manifest")
	dir_rel = _session(tmp_path, meta=meta)
	result = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=gating.current_pipeline())
	assert result["action"] == "skip"


def test_legacy_sin_manifest_version_vieja_procesa(tmp_path):
	meta = _meta()
	meta.pop("manifest")
	meta["annotate_prompt_version"] = "p1:viejo"
	dir_rel = _session(tmp_path, meta=meta)
	result = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=gating.current_pipeline())
	assert result["action"] == "process"
	assert "legacy" in result["reason"]


def test_mark_outcome_actualiza_latest_y_history(tmp_path):
	dir_rel = _session(tmp_path, meta=_meta(), partial=True)
	result = gating.gate_session(tmp_path, dir_rel, run_id="r1", pipeline=gating.current_pipeline())
	assert result["state"] == "pending"
	gating.mark_outcome(tmp_path, dir_rel, run_id="r1", state="done", outcome={"status": "ok", "notas": 4})
	gate = gating.read_gate(tmp_path, dir_rel)
	assert gate["latest"]["state"] == "done"
	assert gate["latest"]["outcome"]["notas"] == 4
	assert gate["history"][-1]["state"] == "done"


def test_input_cambiado_dispara_process(tmp_path):
	dir_rel = _session(tmp_path, meta=_meta())
	pipeline = gating.current_pipeline()
	gating.seal(
		tmp_path, dir_rel, run_id="r1", action="skip", state="skipped",
		reason="sin delta", to_fingerprint=pipeline["manifest_hash"], input_hash="hash-viejo",
	)
	result = gating.gate_session(tmp_path, dir_rel, run_id="r2", pipeline=pipeline)
	assert result["action"] == "process"
	assert "input" in result["reason"]


def test_delta_mixto_usa_prioridad(tmp_path):
	annotate_dir = tmp_path / "a"
	annotate_dir.mkdir()
	pipeline = gating.current_pipeline()
	action, _ = gating.predicate_action(["bio", "extract_work"], {}, {}, annotate_dir, pipeline)
	assert action == "process"  # extract manda sobre bio (que sería skip)
	action, _ = gating.predicate_action(["voice_rewrite_prompt", "dual_score"], {"flags": {}}, {"pct_primera_persona": 100.0}, annotate_dir, pipeline)
	assert action == "rescore"  # scorer manda sobre voz limpia (skip)


def test_record_path_bloquea_traversal(tmp_path):
	from red_pill.memento.record import update_session_record

	with pytest.raises(ValueError):
		update_session_record(tmp_path, "../fuera", "gate", {"stage": "gate"})
