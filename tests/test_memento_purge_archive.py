"""Fase 4 §6.8: purga de archive_memories (backup previo) + eliminación de chronicle_distill/refine."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_purge_module():
	spec = importlib.util.spec_from_file_location("memento_purge_archive", Path("scripts/memento_purge_archive.py"))
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def _make_coverage_registry(tmp_path: Path, no_raw: list[str]):
	registry = {"registry": {}}
	for sid in ("s1", "s2", "s3"):
		registry["registry"].setdefault("opencode", {})[f"opencode:{sid}"] = {"dir": f"2026-09/opencode/opencode-{sid}"}
	reg_path = tmp_path / "memento_registry.json"
	reg_path.write_text(json.dumps(registry), encoding="utf-8")
	for sid in ("s1", "s2", "s3"):
		if sid in no_raw:
			continue
		(raw_dir := tmp_path / f"2026-09/opencode/opencode-{sid}/raw").mkdir(parents=True, exist_ok=True)
		(raw_dir / "raw.jsonl").write_text("[]", encoding="utf-8")
	return reg_path


class _RegistryOverride:
	def __init__(self, path):
		self.path = path

	def __call__(self, *a, **kw):
		reg = type("R", (), {})()
		reg.state = {"registry": json.loads(self.path.read_text())["registry"]}
		return reg


def test_raw_coverage_counts_missing(tmp_path: Path, monkeypatch):
	import red_pill.memento.registry as reg_mod

	reg_path = _make_coverage_registry(tmp_path, no_raw=["s3"])
	monkeypatch.setattr(reg_mod, "MementoRegistry", _RegistryOverride(reg_path))

	purge = _load_purge_module()
	cov = purge._raw_coverage(tmp_path)
	assert cov["total"] == 3
	assert cov["with_raw"] == 2
	assert cov["missing"] == ["opencode|opencode:s3"]


def test_legacy_scripts_removed():
	assert not Path("scripts/chronicle_distill.py").exists()
	assert not Path("scripts/chronicle_refine.py").exists()


def test_purge_script_exists_and_dry_runs():
	script = Path("scripts/memento_purge_archive.py")
	assert script.exists()
	src = script.read_text(encoding="utf-8")
	assert "--apply" in src  # dry-run por defecto
	assert "create_bunker_snapshot" in src  # backup previo obligatorio
	assert "delete_collection" in src
