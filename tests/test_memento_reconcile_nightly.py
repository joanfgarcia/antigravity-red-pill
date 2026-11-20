"""La reconciliación de huérfanos corre cada noche tras annotate (E-97e9d2).

Dos piezas: el flag `--reconcile-only` (no asciende: eso ya lo hace su etapa) y
el cableado en `chronicle.yaml` detrás de `memento-annotate`.
"""

import importlib.util
import json
import sys
from pathlib import Path

import yaml


def _load_script():
	spec = importlib.util.spec_from_file_location("memento_ascend_script", Path("scripts/memento_ascend.py"))
	assert spec is not None and spec.loader is not None
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_reconcile_only_no_asciende(monkeypatch, capsys):
	import red_pill.memento.ascension as ascension

	mod = _load_script()
	llamadas = []

	def boom(*a, **k):
		llamadas.append("ascend")
		raise AssertionError("--reconcile-only no debe ascender")

	def fake_reconcile(root, dry_run=False, **k):
		llamadas.append(("reconcile", dry_run))
		return {"revisados": 10, "huerfanos": 2, "omitidos_sesion_a_medias": 1, "por_coleccion": {}, "dry_run": dry_run}

	monkeypatch.setattr(mod, "ascend_by_threshold", boom)
	monkeypatch.setattr(ascension, "reconcile_orphans", fake_reconcile)
	monkeypatch.setattr(sys, "argv", ["memento_ascend.py", "--reconcile-only", "--dry-run", "--root", "/tmp/nada"])

	mod.main()

	assert llamadas == [("reconcile", True)]
	out = json.loads(capsys.readouterr().out)
	assert out["reconcile"]["huerfanos"] == 2


def test_chronicle_encadena_reconcile_tras_annotate():
	job = yaml.safe_load(Path("configs/jobs/chronicle.yaml").read_text(encoding="utf-8"))
	stages = {s["id"]: s for s in job["manifest"]["stages"]}
	assert "memento-reconcile" in stages
	rec = stages["memento-reconcile"]
	assert "--reconcile-only" in rec["command"]
	assert rec["depends_on"] == ["memento-annotate"]
	assert rec.get("on_fail") == "warn"
	assert stages["memento-backlog"]["depends_on"] == ["memento-reconcile"]
