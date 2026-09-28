"""Cobertura del archivo Memento por sesión: raw O render (migrador single-writer)."""

from __future__ import annotations

from pathlib import Path

from red_pill.memento.coverage import classify_session, coverage


class _FakeRegistry:
	def __init__(self, registry):
		self.state = {"registry": registry}


def _touch(p: Path):
	p.mkdir(parents=True, exist_ok=True)
	(p / "x.md").write_text("x", encoding="utf-8")


def test_classify_raw(tmp_path):
	d = tmp_path / "s1"
	_touch(d / "raw")
	assert classify_session(tmp_path, "s1") == "raw"


def test_classify_rendered_si_raw_vacio(tmp_path):
	d = tmp_path / "s2"
	(d / "raw").mkdir(parents=True)
	_touch(d / "memento")
	assert classify_session(tmp_path, "s2") == "rendered"


def test_classify_none(tmp_path):
	(tmp_path / "s3").mkdir(parents=True)
	(tmp_path / "s3" / "raw").mkdir()
	assert classify_session(tmp_path, "s3") is None


def test_coverage_cuenta_raw_y_rendered(tmp_path):
	_touch(tmp_path / "a" / "raw")
	(tmp_path / "b" / "raw").mkdir(parents=True)
	_touch(tmp_path / "b" / "annotate")
	(tmp_path / "c").mkdir(parents=True)
	reg = _FakeRegistry({"telegram": {"s1": {"dir": "a"}, "s2": {"dir": "b"}, "s3": {"dir": "c"}}})
	cov = coverage(tmp_path, registry=reg)
	assert cov["total"] == 3
	assert cov["raw"] == 1 and cov["rendered"] == 1
	assert cov["covered"] == 2
	assert cov["missing"] == ["telegram|s3"]


def test_coverage_ignora_sin_dir(tmp_path):
	reg = _FakeRegistry({"opencode": {"sid": {}}})
	cov = coverage(tmp_path, registry=reg)
	assert cov["total"] == 0 and cov["missing"] == []
