"""Tests del wiring de AWAKEN-002: directiva del despertar y digest A-1."""

from __future__ import annotations

import importlib
import time
from pathlib import Path

from red_pill.core import awakening_channel as ch


def _note(desk: Path, target: str) -> Path:
	ch.ensure_channel(desk)
	f = desk / "awakening" / "notes" / "n.md"
	f.write_text(f"---\npara: {target}\n---\n\n# Decisión\n", encoding="utf-8")
	return f


def test_directiva_canal_apunta_al_indice(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path))
	worker = importlib.import_module("red_pill.core.agent_worker")
	out = worker._awakening_channel_directive()
	assert "AWAKEN-002" in out
	assert "planner/design/AWAKEN-002-despertares-utiles/INDEX.md" in out
	assert "README.md" not in out
	assert "awakening/notes/" in out
	# El placeholder se resuelve al emitir: el agente nunca debe leer `${AGENT_CORE_DIR}`.
	assert "${" not in out
	assert str(tmp_path) in out


def test_resolve_desk_paths_sustituye_el_placeholder(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path))
	worker = importlib.import_module("red_pill.core.agent_worker")
	assert worker._resolve_desk_paths("lee ${AGENT_CORE_DIR}/awakening/") == f"lee {tmp_path}/awakening/"


def test_resolve_desk_paths_sin_placeholder_no_toca_el_texto():
	worker = importlib.import_module("red_pill.core.agent_worker")
	text = "texto sin puntero (planner/ideas/)"
	assert worker._resolve_desk_paths(text) == text


def test_resolve_desk_paths_no_lanza_si_el_desk_no_resuelve(monkeypatch):
	worker = importlib.import_module("red_pill.core.agent_worker")

	def boom():
		raise RuntimeError("desk irresoluble")

	monkeypatch.setattr(worker, "get_agent_core_root", boom)
	text = "desk: ${AGENT_CORE_DIR}/awakening/"
	assert worker._resolve_desk_paths(text) == text


def test_directiva_cuenta_notas_pendientes(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path))
	operator = ch.operator_name()
	_note(tmp_path, operator)
	worker = importlib.import_module("red_pill.core.agent_worker")
	out = worker._awakening_channel_directive()
	assert "1 nota(s)" in out


def test_directiva_sin_desk_no_lanza(tmp_path, monkeypatch):
	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path / "no-existe"))
	worker = importlib.import_module("red_pill.core.agent_worker")
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


def test_lease_keeper_mantiene_el_latido_y_lo_para():
	worker = importlib.import_module("red_pill.core.agent_worker")

	class Fake:
		def __init__(self):
			self.n = 0

		def _touch_lease(self):
			self.n += 1

	f = Fake()
	with worker.IDEWorker._lease_keeper(f, interval=0.02):
		time.sleep(0.12)
	n = f.n
	assert n >= 2
	time.sleep(0.08)
	assert f.n == n
