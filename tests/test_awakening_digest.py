"""Tests del wiring de AWAKEN-002: directiva del despertar y digest A-1."""

from __future__ import annotations

import importlib
from pathlib import Path

from red_pill.core import awakening_channel as ch


def _note(desk: Path, target: str) -> Path:
	ch.ensure_channel(desk)
	f = desk / "awakening" / "notes" / "n.md"
	f.write_text(f"---\npara: {target}\n---\n\n# Decisión\n", encoding="utf-8")
	return f


def test_directiva_canal_apunta_al_indice(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path))
	worker = importlib.import_module("red_pill.plugins.antigravity_ide.worker")
	out = worker._awakening_channel_directive()
	assert "AWAKEN-002" in out
	assert "planner/design/AWAKEN-002-despertares-utiles/README.md" in out
	assert "awakening/notes/" in out


def test_directiva_cuenta_notas_pendientes(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path))
	operator = ch.operator_name()
	_note(tmp_path, operator)
	worker = importlib.import_module("red_pill.plugins.antigravity_ide.worker")
	out = worker._awakening_channel_directive()
	assert "1 nota(s)" in out


def test_directiva_sin_desk_no_lanza(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path / "no-existe"))
	worker = importlib.import_module("red_pill.plugins.antigravity_ide.worker")
	assert "AWAKEN-002" in worker._awakening_channel_directive()


def test_telemetry_digest_incluye_notas(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path))
	operator = ch.operator_name()
	_note(tmp_path, operator)
	mod = importlib.import_module("red_pill.interceptors.01_telemetry")
	line = mod.TelemetryPlugin()._notes_line()
	assert "decisión(es) pendiente" in line
	assert operator in line


def test_telemetry_digest_sin_notas(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path))
	mod = importlib.import_module("red_pill.interceptors.01_telemetry")
	assert mod.TelemetryPlugin()._notes_line() == ""
