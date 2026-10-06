"""MEM-010 F2b: integración del gate en el CLI de annotate y en el nocturno.

Aislamiento: `tmp_path` + transporte falso/monkeypatch; sin servicios vivos.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import red_pill.config as cfg
from red_pill.memento import gating


def _load_script():
	spec = importlib.util.spec_from_file_location("memento_annotate_script_b", Path("scripts/memento_annotate.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def _session(tmp_path: Path, name: str, *, meta=None, notes=None, partial=False) -> str:
	dir_rel = f"2026-09/opencode/{name}"
	session = tmp_path / dir_rel
	(session / "memento").mkdir(parents=True)
	(session / "memento" / "index.md").write_text("# s\n\nJoan me pide algo.\n", encoding="utf-8")
	(session / "annotate").mkdir(exist_ok=True)
	if meta is not None:
		(session / "annotate" / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
	for i, text in enumerate(notes or []):
		(session / "annotate" / f"00{i}-n.md").write_text(
			f"---\ntitle: t{i}\nwork_score: 0.9\nsocial_score: 0.1\n---\n{text}\n", encoding="utf-8"
		)
	if partial:
		(session / "annotate" / "_partial.json").write_text("{}", encoding="utf-8")
	return dir_rel


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


def _voice_meta(**over):
	manifest = json.loads(json.dumps(gating.current_pipeline()["manifest"]))
	manifest["components"]["voice_rewrite_prompt"] = "p1:viejo"
	return _meta(manifest=manifest, **over)


def _run(monkeypatch, capsys, mod, argv):
	monkeypatch.setattr(sys, "argv", ["memento_annotate.py", *argv])
	mod.main()
	return json.loads(capsys.readouterr().out)


# ── --list con gate ──────────────────────────────────────────────────────────


def test_list_con_gate_emite_solo_lo_que_toca_y_es_idempotente(tmp_path, monkeypatch, capsys):
	mod = _load_script()
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_GATE", True, raising=False)
	monkeypatch.setattr(mod, "_current_engine", lambda: "test-engine")
	skip_dir = _session(tmp_path, "skip", meta=_meta())
	voice_dir = _session(tmp_path, "voice", meta=_voice_meta(flags={"voice": 2}))

	first = _run(monkeypatch, capsys, mod, ["--list", "--root", str(tmp_path)])
	assert [(e["dir"], e["action"]) for e in first] == [(voice_dir, "process")]
	assert all(e.get("run_id") for e in first)  # MEM-010 F3: el elemento lleva su run
	skip_record = tmp_path / skip_dir / "_session.json"
	after_first = skip_record.read_text(encoding="utf-8")

	second = _run(monkeypatch, capsys, mod, ["--list", "--root", str(tmp_path)])
	assert second == first
	assert skip_record.read_text(encoding="utf-8") == after_first  # fast-path: sin re-sellado
	voice_gate = gating.read_gate(tmp_path, voice_dir)
	assert len(voice_gate["history"]) == 1  # upsert entre re-invocaciones


def test_status_desglosa_saltadas_por_razon(tmp_path, monkeypatch, capsys):
	mod = _load_script()
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_GATE", True, raising=False)
	monkeypatch.setattr(mod, "_current_engine", lambda: "test-engine")
	_session(tmp_path, "skip", meta=_meta())
	_session(tmp_path, "voice", meta=_voice_meta(flags={"voice": 2}))
	_run(monkeypatch, capsys, mod, ["--list", "--root", str(tmp_path)])
	status = _run(monkeypatch, capsys, mod, ["--status", "--root", str(tmp_path)])
	assert status["gate"]["acciones"] == {"skip": 1, "process": 1}
	assert sum(status["gate"]["motivos_skip"].values()) == 1


# ── process_one: enrutado por acción + outcome ───────────────────────────────


def test_process_one_enruta_rescore_y_sella_outcome(tmp_path, monkeypatch):
	mod = _load_script()
	pipeline = gating.current_pipeline()
	calls = []

	def fake_annotate(root, dir_rel, session_id, source, transport, **kw):
		calls.append(kw.get("from_phase"))
		(root / dir_rel / "annotate" / "001-n.md").write_text("---\n---\nnota\n", encoding="utf-8")
		return 0.9

	monkeypatch.setattr(mod, "annotate_session", fake_annotate)
	monkeypatch.setattr(mod, "_canonical_ids", lambda: {})
	run_id = mod._run_id(pipeline)

	for name, action, expected_phase in (("p1", "process", None), ("p2", "rescore", "score")):
		dir_rel = _session(tmp_path, name, meta=_meta())
		gating.seal(
			tmp_path, dir_rel, run_id=run_id, action=action, state="pending",
			reason="test", to_fingerprint=pipeline["manifest_hash"],
		)
		result = mod.process_one(tmp_path, dir_rel, action=action)
		assert result["anotaciones"] == 1
		gate = gating.read_gate(tmp_path, dir_rel)
		assert gate["latest"]["state"] == "done"
		assert gate["latest"]["outcome"]["notas"] == 1
	assert calls == [None, "score"]


def test_process_one_legacy_respeta_fresh(tmp_path, monkeypatch):
	mod = _load_script()
	dir_rel = _session(tmp_path, "legacy", meta=_meta())
	calls = []
	monkeypatch.setattr(mod, "_fresh", lambda *a, **k: True)
	monkeypatch.setattr(mod, "annotate_session", lambda *a, **k: calls.append(1) or 0.0)
	assert mod.process_one(tmp_path, dir_rel) == {"dir": dir_rel, "skipped": "fresh"}
	assert calls == []


def test_process_one_sella_failed_al_fallar(tmp_path, monkeypatch):
	mod = _load_script()
	pipeline = gating.current_pipeline()
	dir_rel = _session(tmp_path, "boom", meta=_meta())
	gating.seal(
		tmp_path, dir_rel, run_id=mod._run_id(pipeline), action="process", state="pending",
		reason="test", to_fingerprint=pipeline["manifest_hash"],
	)

	def boom(*a, **k):
		raise ValueError("fallo de extract")

	monkeypatch.setattr(mod, "annotate_session", boom)
	monkeypatch.setattr(mod, "_canonical_ids", lambda: {})
	with pytest.raises(ValueError):
		mod.process_one(tmp_path, dir_rel, action="process")
	gate = gating.read_gate(tmp_path, dir_rel)
	assert gate["latest"]["state"] == "failed"
	assert "fallo de extract" in gate["latest"]["outcome"]["error"]


# ── migración one-shot ───────────────────────────────────────────────────────


def test_gate_migrate_dry_run_y_adopcion(tmp_path, monkeypatch, capsys):
	mod = _load_script()
	legacy = _meta()
	legacy.pop("manifest")
	adopt_dir = _session(tmp_path, "adopt", meta=legacy, notes=["Joan me pide algo concreto."])
	old = _meta()
	old.pop("manifest")
	old["annotate_prompt_version"] = "p1:viejo"
	old_dir = _session(tmp_path, "old", meta=old)
	fresh_dir = _session(tmp_path, "fresh", meta=_meta())

	dry = _run(monkeypatch, capsys, mod, ["--gate-migrate", "--dry-run", "--root", str(tmp_path)])
	assert dry == {"dry_run": True, "fresh": 1, "adopted": 1, "legacy-unknown": 1, "sin-meta": 0, "error": 0}
	assert "manifest" not in json.loads((tmp_path / adopt_dir / "annotate" / "_meta.json").read_text())

	real = _run(monkeypatch, capsys, mod, ["--gate-migrate", "--root", str(tmp_path)])
	assert real["adopted"] == 1
	meta = json.loads((tmp_path / adopt_dir / "annotate" / "_meta.json").read_text())
	assert meta["manifest"]["schema"] == "gate-manifest-v1"
	assert meta["metrics"]["notas"] == 1
	assert meta["input_hash"]
	old_meta = json.loads((tmp_path / old_dir / "annotate" / "_meta.json").read_text())
	assert "manifest" not in old_meta  # legacy-unknown: no se toca
	fresh_meta = json.loads((tmp_path / fresh_dir / "annotate" / "_meta.json").read_text())
	assert fresh_meta["manifest"]["schema"] == "gate-manifest-v1"


# ── nocturno: consulta (solo lectura) ────────────────────────────────────────


def test_nocturno_consulta_gate_sin_sellar(tmp_path, monkeypatch):
	from red_pill.memento.agentic import runner

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", True, raising=False)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_GATE", True, raising=False)
	process_dir = _session(tmp_path, "voice", meta=_voice_meta(flags={"voice": 2}))
	skip_dir = _session(tmp_path, "skip", meta=_meta())
	registry = SimpleNamespace(state={"registry": {"opencode": {"s1": {"dir": process_dir}, "s2": {"dir": skip_dir}}}})
	pending = runner.pending_agentic(registry, root=tmp_path)
	assert pending == [("opencode", "s1", "missing")]
	# Consulta de solo lectura: el nocturno no sella decisiones.
	assert not (tmp_path / process_dir / "_session.json").exists()
	assert not (tmp_path / skip_dir / "_session.json").exists()
