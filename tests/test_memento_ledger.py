"""MEM-010 F3: ledger global (saneado, rotación, cierre) y remediación --rebuild-run."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from red_pill.memento import gating, ledger


def _load_script():
	spec = importlib.util.spec_from_file_location("memento_annotate_script_c", Path("scripts/memento_annotate.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
	monkeypatch.setattr(ledger, "ledger_path", lambda: tmp_path / "state" / "rebuilds.json")
	return tmp_path


def _session(tmp_path: Path, name: str, *, meta=None) -> str:
	dir_rel = f"2026-09/opencode/{name}"
	session = tmp_path / dir_rel
	(session / "memento").mkdir(parents=True)
	(session / "memento" / "index.md").write_text("# s\n\nJoan me pide algo.\n", encoding="utf-8")
	(session / "annotate").mkdir(exist_ok=True)
	if meta is not None:
		(session / "annotate" / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
	return dir_rel


def _meta():
	pipeline = gating.current_pipeline()
	return {
		"engine": "test-engine",
		"annotate_prompt_version": pipeline["legacy_fingerprint"],
		"manifest": pipeline["manifest"],
		"metrics": {"pct_primera_persona": 100.0, "min_margin": 0.5, "bio_leaks": 0, "near_dups": 0, "dedup_threshold": 0.6},
		"flags": {},
		"routes": {"work": 1, "social": 0, "none": 0},
		"notas": 1,
	}


# ── ledger ───────────────────────────────────────────────────────────────────


def test_sanitize_quita_ansi_rutas_y_capa():
	raw = "\x1b[31mfallo en /home/joan/Documents/IA/sharing/src/x.py\x1b[0m"
	out = ledger.sanitize_text(raw, ledger.ERROR_CAP)
	assert "\x1b" not in out and "/home/joan" not in out and "x.py" in out
	assert len(ledger.sanitize_text("palabra " * 200, 512)) == 512
	assert len(ledger.sanitize_text("x" * 5000, 512)) <= 512  # scrub puede redactar antes del cap


def test_open_rotate_decisions_counts_y_modo(tmp_ledger):
	for i in range(12):
		ledger.open_run(run_id=f"r{i}", stage="annotate", to_fingerprint="h")
	runs = ledger.load_runs()
	assert len(runs) == ledger.RUNS_CAP
	assert runs[0]["run_id"] == "r2"  # FIFO
	ledger.open_run(run_id="r11", stage="annotate", to_fingerprint="h")  # reanudar no duplica
	assert len(ledger.load_runs()) == ledger.RUNS_CAP
	ledger.record_decisions("r11", {"a/b": {"action": "skip", "reason": "sin delta"}, "a/c": {"action": "process", "reason": "delta"}})
	ledger.bump_counts("r11", "processed")
	ledger.set_counts("r11", skipped=1)
	run = next(r for r in ledger.load_runs() if r["run_id"] == "r11")
	assert run["counts"] == {"processed": 1, "skipped": 1, "rescored": 0, "failed": 0}
	assert run["decisions"]["a/b"]["action"] == "skip"
	mode = oct(ledger.ledger_path().stat().st_mode & 0o777)
	assert mode == "0o600"


def test_cierre_con_senal(tmp_ledger):
	ledger.open_run(run_id="rA", stage="annotate", to_fingerprint="h")
	ledger.open_run(run_id="rB", stage="annotate", to_fingerprint="h")
	closed = ledger.close_stale_runs(resolutions={"rA": "closed"})
	assert closed == ["rA", "rB"]  # cierra todo run abierto; rA por resolución, rB conservador
	runs = {r["run_id"]: r for r in ledger.load_runs()}
	assert runs["rA"]["status"] == "closed" and runs["rA"]["finished_at"]
	assert runs["rB"]["status"] == "closed-incomplete"  # sin resolución: conservador
	assert ledger.close_stale_runs() == []  # ya no queda ninguno abierto


# ── remediación CLI ──────────────────────────────────────────────────────────


def test_rebuild_run_re_sella_y_emite(tmp_path, tmp_ledger, monkeypatch, capsys):
	mod = _load_script()
	monkeypatch.setattr(ledger, "ledger_path", lambda: tmp_path / "state" / "rebuilds.json")
	d1 = _session(tmp_path, "uno", meta=_meta())
	d2 = _session(tmp_path, "dos", meta=_meta())
	ledger.open_run(run_id="orig1", stage="annotate", to_fingerprint="h")
	ledger.record_decisions("orig1", {d1: {"action": "processed", "reason": ""}, d2: {"action": "skipped", "reason": "sin delta"}})

	monkeypatch.setattr(sys, "argv", ["memento_annotate.py", "--rebuild-run", "orig1", "--actions", "processed", "--root", str(tmp_path)])
	mod.main()
	elements = json.loads(capsys.readouterr().out)
	assert [e["dir"] for e in elements] == [d1]
	new_run = elements[0]["run_id"]
	assert new_run.startswith("orig1-rb-")
	gate = gating.read_gate(tmp_path, d1)
	assert gate["latest"]["action"] == "forced" and gate["latest"]["state"] == "pending"
	assert gate["latest"]["run_id"] == new_run
	# Segunda invocación: mismo run nuevo (idempotente, sin duplicar historial)
	monkeypatch.setattr(sys, "argv", ["memento_annotate.py", "--rebuild-run", "orig1", "--actions", "processed", "--root", str(tmp_path)])
	mod.main()
	capsys.readouterr()
	assert gating.read_gate(tmp_path, d1)["latest"]["run_id"] == new_run
	assert len(gating.read_gate(tmp_path, d1)["history"]) == 1
	# El run original queda registrado y el nuevo abierto con su subset
	runs = {r["run_id"]: r for r in ledger.load_runs()}
	assert runs[new_run]["status"] == "open"
	assert d1 in runs[new_run]["decisions"]


def test_runs_lista_el_ledger(tmp_path, tmp_ledger, monkeypatch, capsys):
	mod = _load_script()
	ledger.open_run(run_id="rZ", stage="annotate", to_fingerprint="h")
	monkeypatch.setattr(sys, "argv", ["memento_annotate.py", "--runs"])
	mod.main()
	runs = json.loads(capsys.readouterr().out)
	assert runs and runs[0]["run_id"] == "rZ"


def test_process_one_cuenta_en_ledger(tmp_path, tmp_ledger, monkeypatch):
	mod = _load_script()
	monkeypatch.setattr(ledger, "ledger_path", lambda: tmp_path / "state" / "rebuilds.json")
	dir_rel = _session(tmp_path, "cuenta", meta=_meta())
	ledger.open_run(run_id="rC", stage="annotate", to_fingerprint="h")
	gating.seal(
		tmp_path, dir_rel, run_id="rC", action="process", state="pending",
		reason="test", to_fingerprint=gating.current_pipeline()["manifest_hash"],
	)
	monkeypatch.setattr(mod, "_canonical_ids", lambda: {})
	monkeypatch.setattr(mod, "annotate_session", lambda *a, **k: 0.5)
	mod.process_one(tmp_path, dir_rel, action="process", run_id="rC")
	run = next(r for r in ledger.load_runs() if r["run_id"] == "rC")
	assert run["counts"]["processed"] == 1
	assert gating.read_gate(tmp_path, dir_rel)["latest"]["state"] == "done"
