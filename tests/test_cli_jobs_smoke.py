"""Smoke tests for cli_jobs common paths (SHARD-PV-02). No edge cases."""

from __future__ import annotations

import argparse

from red_pill.cli_jobs import _confirm, _format_progress, _purge_jobs


def test_confirm_yes_and_eof(monkeypatch):
	monkeypatch.setattr("builtins.input", lambda _p="": "y")
	assert _confirm("?") is True
	monkeypatch.setattr("builtins.input", lambda _p="": "n")
	assert _confirm("?") is False

	def _eof(_p=""):
		raise EOFError

	monkeypatch.setattr("builtins.input", _eof)
	assert _confirm("?") is False


def test_purge_jobs_sin_objetivo_avisa(capsys):
	# Sin ids y sin --terminal: avisa y NO toca la cola (queue puede ser None).
	_purge_jobs(None, argparse.Namespace(job_ids=[], terminal=False))
	assert "[ERROR]" in capsys.readouterr().out


def test_format_progress_vacio_y_con_datos():
	assert _format_progress({}) == "-"
	assert _format_progress({"current": 3, "total": 9}) == "3/9"
