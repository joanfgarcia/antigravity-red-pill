"""E-97e9d2: auditoría read-only de pérdidas silenciosas en Memento.

El script es un watchdog, así que lo que hay que fijar es su capacidad de
distinguir las firmas: sellado sin notas (rama rota), índice vs registry
desincronizados, `refine/` vacío y `annotate/` ejecutado sin extraer ideas.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_script():
	spec = importlib.util.spec_from_file_location("audit_memento_silent_loss", Path("scripts/audit_memento_silent_loss.py"))
	assert spec is not None and spec.loader is not None
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def _session(tmp_path: Path, name: str, *, sig_registry, sig_index="0.0", notes=0, annotate_dir=True, refine_dir=False, distilled_at="2026-11-01T00:00:00+00:00", sealed=True):
	dir_rel = f"2026-11/{name}"
	base = tmp_path / dir_rel
	(base / "memento").mkdir(parents=True)
	(base / "memento" / "index.md").write_text(f"---\nsignificance: {sig_index}\n---\n\ncuerpo\n", encoding="utf-8")
	if annotate_dir:
		(base / "annotate").mkdir()
		for i in range(notes):
			(base / "annotate" / f"00{i}-n.md").write_text("---\ntitle: t\n---\nnota\n", encoding="utf-8")
	if refine_dir:
		(base / "refine").mkdir()
	agentic = {
		"distilled_at": distilled_at,
		"hash": "h1" if sealed else None,
		"max_significance": sig_registry,
		"annotate_pending": False if sealed else True,
	}
	return dir_rel, {"dir": dir_rel, "memento_hash": "h1", "agentic": agentic}


def test_audit_detecta_las_firmas_y_ignora_el_ruido(tmp_path, monkeypatch):
	mod = _load_script()
	registry_rows = {}

	rows = [
		_session(tmp_path, "rota", sig_registry=0.0, annotate_dir=False),  # FAIL sellada sin notas
		_session(tmp_path, "sana", sig_registry=0.9, sig_index="0.9", notes=2),  # OK
		_session(tmp_path, "sin_ideas", sig_registry=0.0, notes=0),  # INFO: annotate corrió, 0 notas
		_session(tmp_path, "mismatch", sig_registry=0.9, sig_index="0.3", notes=1),  # FAIL índice ≠ registry
		_session(tmp_path, "refine_vacio", sig_registry=0.5, sig_index="0.5", notes=1, refine_dir=True),  # WARN
		_session(tmp_path, "pre_era", sig_registry=0.0, annotate_dir=False, distilled_at="2026-09-01T00:00:00+00:00"),  # fuera de alcance
	]
	for i, (dir_rel, entry) in enumerate(rows):
		registry_rows[f"s{i}"] = entry

	monkeypatch.setattr("red_pill.memento.get_memento_root", lambda: tmp_path)
	monkeypatch.setattr("red_pill.memento.registry.MementoRegistry", lambda: SimpleNamespace(state={"registry": {"opencode": registry_rows}}))

	report = mod.audit(mod.ANNOTATE_PHASE_ERA)

	checks = sorted((f["check"], f["session"]) for f in report["fails"])
	assert checks == [("index_registry_mismatch", "s3"), ("sealed_without_notes", "s0")]
	assert [w["session"] for w in report["warns"]] == ["s4"]
	assert [z["session"] for z in report["zero_notes"]] == ["s2"]
	assert report["skipped_pre_era"] == 1
	assert report["scanned"] == 5


def test_audit_arbol_limpio_sale_en_cero(tmp_path, monkeypatch, capsys):
	mod = _load_script()
	dir_rel, entry = _session(tmp_path, "sana", sig_registry=0.9, sig_index="0.9", notes=1)
	monkeypatch.setattr("red_pill.memento.get_memento_root", lambda: tmp_path)
	monkeypatch.setattr("red_pill.memento.registry.MementoRegistry", lambda: SimpleNamespace(state={"registry": {"opencode": {"s0": entry}}}))
	monkeypatch.setattr("sys.argv", ["audit_memento_silent_loss.py"])

	mod.main()  # sin SystemExit: exit 0

	out = capsys.readouterr().out
	assert "0 fallo(s), 0 aviso(s)" in out
