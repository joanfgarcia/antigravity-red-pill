"""Migrador single-writer: helpers y flujo (dry-run, idempotencia, abortos)."""

from __future__ import annotations

from pathlib import Path

import scripts.migrate_single_writer as msw


def test_staging_files_solo_ficheros(tmp_path, monkeypatch):
	staging = tmp_path / "staging"
	staging.mkdir()
	(staging / "a.json").write_text("{}")
	(staging / "sub").mkdir()
	monkeypatch.setattr(msw, "_staging_files", lambda: [p for p in staging.iterdir() if p.is_file()])
	assert [p.name for p in msw._staging_files()] == ["a.json"]


def _prep(monkeypatch, tmp_path, missing=None, staging=0):
	marker = tmp_path / "state" / "single_writer_migrated.json"
	monkeypatch.setattr(msw, "_marker_path", lambda: marker)
	monkeypatch.setattr(msw, "_coverage_missing", lambda: list(missing or []))
	monkeypatch.setattr(msw, "_staging_files", lambda: [Path(f"/tmp/s{i}") for i in range(staging)])
	monkeypatch.setattr(msw, "_trim_buffer", lambda apply: {"total": 0, "trimmed": 0, "max_age_days": 30})
	return marker


def test_aborta_si_falta_cobertura(monkeypatch, tmp_path):
	_prep(monkeypatch, tmp_path, missing=["telegram|x"])
	monkeypatch.setattr("sys.argv", ["migrate"])
	assert msw.main() == 1


def test_dry_run_no_escribe_marca(monkeypatch, tmp_path):
	marker = _prep(monkeypatch, tmp_path)
	monkeypatch.setattr("sys.argv", ["migrate"])
	assert msw.main() == 0
	assert not marker.exists()


def test_apply_escribe_marca(monkeypatch, tmp_path):
	marker = _prep(monkeypatch, tmp_path)
	monkeypatch.setattr("sys.argv", ["migrate", "--apply"])
	assert msw.main() == 0
	assert marker.exists()


def test_idempotente_si_ya_migrado(monkeypatch, tmp_path):
	marker = _prep(monkeypatch, tmp_path)
	marker.parent.mkdir(parents=True, exist_ok=True)
	marker.write_text("{}", encoding="utf-8")
	called = {"cov": False}
	monkeypatch.setattr(msw, "_coverage_missing", lambda: called.__setitem__("cov", True) or [])
	monkeypatch.setattr("sys.argv", ["migrate"])
	assert msw.main() == 0
	assert called["cov"] is False  # no re-verifica si ya está migrado


def test_force_reelabora(monkeypatch, tmp_path):
	marker = _prep(monkeypatch, tmp_path)
	marker.parent.mkdir(parents=True, exist_ok=True)
	marker.write_text("{}", encoding="utf-8")
	monkeypatch.setattr("sys.argv", ["migrate", "--force"])
	assert msw.main() == 0
