"""ARCH-001 — E2E de la pieza completa (no unitarios de trozos).

Objetivo: asegurar que el worker refactorizado (paso A+B, core agnóstico +
estrategia de pulse) SIGUE funcionando de punta a punta: un mensaje entra por el
inbox, atraviesa el worker real (construido como en producción), el bridge lo
responde, y sale por el outbox con el estado correcto — y la estrategia de pulse
se ejerce (no se queda en no-op).

Se construye el `IDEWorker` REAL (parcheando solo las fronteras de red: bridges y
Samantha), exactamente como hacen los tests de integración existentes. No se
mockea el worker ni `process_inbox`/`run_once`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.core.agent_worker import IDEWorker
from red_pill.swarm.bridges import BackendType, BridgeCapabilities


def _seed_events_db(db_path: Path) -> None:
	conn = sqlite3.connect(str(db_path))
	conn.executescript(
		"""
		CREATE TABLE inbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE,
			channel TEXT NOT NULL, channel_user_id TEXT NOT NULL, cascade_id TEXT,
			payload TEXT NOT NULL, status TEXT DEFAULT 'PENDING',
			retries INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
		CREATE TABLE outbox (
			id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, channel_user_id TEXT,
			cascade_id TEXT, payload TEXT
		);
		CREATE TABLE telegram_sessions (
			channel_user_id TEXT PRIMARY KEY, cascade_id TEXT, cascade_type TEXT,
			model TEXT, backend TEXT, accumulated_len INTEGER
		);
		CREATE TABLE cascade_mappings (
			id INTEGER PRIMARY KEY AUTOINCREMENT, channel_user_id TEXT,
			cascade_id TEXT, title TEXT
		);
		CREATE TABLE system_health (
			service_name TEXT PRIMARY KEY, last_heartbeat TIMESTAMP
		);
		"""
	)
	conn.commit()
	conn.close()


class _RecordingBridge:
	"""Bridge determinista: registra los prompts y devuelve una respuesta fija."""

	def __init__(self, response: str = "RESPUESTA-FIJA"):
		self.response = response
		self.prompts: list[str] = []

	def get_capabilities(self):
		return BridgeCapabilities(backend=BackendType.OPENCODE, auto_approve=True)

	def prompt(self, text, timeout=None, **kw):
		self.prompts.append(text)
		return SimpleNamespace(ok=True, response=self.response, text=self.response, error=None, model="fake")


@pytest.fixture
def worker_env(tmp_path, monkeypatch):
	"""Worker REAL + DB real + bridges deterministas. Devuelve (worker, db_path)."""
	db_path = tmp_path / "events.db"
	_seed_events_db(db_path)

	import red_pill.core.agent_worker as worker_module

	monkeypatch.setattr(worker_module, "DB_PATH", db_path)
	monkeypatch.setattr(worker_module, "get_connection", lambda: _conn(db_path))

	# Sesión de Telegram real apuntando a la misma DB.
	import red_pill.telegram.session as tsm_mod

	monkeypatch.setattr(tsm_mod, "get_connection", lambda: _conn(db_path), raising=False)

	monkeypatch.setattr(cfg, "REACTIVE_DEBOUNCE_ENABLED", False)
	monkeypatch.setattr(cfg, "REACTIVE_DEBOUNCE_SECONDS", 0)

	recording = _RecordingBridge()

	class _FakeSamantha:
		def __init__(self, *a, **k):
			pass

		def start(self):
			pass

	monkeypatch.setattr("red_pill.inference.samantha_worker.SamanthaWorker", _FakeSamantha)
	monkeypatch.setattr("red_pill.plugins.antigravity_ide.pulse.AntigravityIDEClient", MagicMock)

	# Construir el worker REAL (ejercita __init__ + _build_strategy + estrategia).
	with patch("red_pill.core.agent_worker.create_cascade_bridge", return_value=recording):
		worker = IDEWorker()

	# Neutralizar efectos de red/estado no deterministas del pulse.
	worker._touch_lease = lambda: None
	worker._signal_samantha_worker = lambda: None
	worker._watchdog_samantha = lambda: None
	worker.update_heartbeat = lambda: None
	worker._scribe_relay = lambda **kw: None

	return worker, db_path, recording


def _conn(db_path: Path):
	c = sqlite3.connect(str(db_path), timeout=10.0)
	c.row_factory = sqlite3.Row
	return c


def _enqueue(db_path: Path, payload: dict, status: str = "PENDING") -> None:
	conn = _conn(db_path)
	conn.execute(
		"INSERT INTO inbox (message_id, channel, channel_user_id, payload, status) VALUES (?,?,?,?,?)",
		("m1", "telegram", "u1", json.dumps(payload), status),
	)
	conn.commit()
	conn.close()


def test_e2e_worker_constructed_with_antigravity_strategy(worker_env):
	"""La pieza se construye como en producción y la estrategia real está activa
	(no degradó al no-op)."""
	from red_pill.plugins.antigravity_ide.pulse import AntigravityPulseStrategy

	worker, _, _ = worker_env
	assert isinstance(worker._strategy, AntigravityPulseStrategy)


def test_e2e_message_flows_inbox_to_outbox(worker_env):
	"""END-TO-END: un mensaje Telegram entra por el inbox y sale por el outbox,
	con el inbox marcado PROCESSED y el bridge habiendo recibido el prompt."""
	worker, db_path, recording = worker_env
	_enqueue(db_path, {"text": "hola mundo", "mode": "conversational"})

	worker.process_inbox()

	conn = _conn(db_path)
	status = conn.execute("SELECT status FROM inbox WHERE message_id='m1'").fetchone()[0]
	outbox = [json.loads(r["payload"])["text"] for r in conn.execute("SELECT payload FROM outbox").fetchall()]
	conn.close()

	assert status == "PROCESSED", f"inbox debe quedar PROCESSED, quedó {status}"
	assert any("RESPUESTA-FIJA" in t for t in outbox), f"la respuesta debe llegar al outbox: {outbox}"
	assert recording.prompts, "el bridge debe haber recibido el prompt"
	assert "hola mundo" in recording.prompts[0], "el prompt debe contener el mensaje del usuario"


def test_e2e_run_once_exercises_strategy_and_message(worker_env):
	"""END-TO-END del pulse completo: run_once() (que ejecuta la estrategia de
	pulse + process_inbox) deja el mensaje procesado y respondido."""
	worker, db_path, recording = worker_env
	_enqueue(db_path, {"text": "mensaje via pulse", "mode": "conversational"})

	worker.run_once()

	conn = _conn(db_path)
	status = conn.execute("SELECT status FROM inbox WHERE message_id='m1'").fetchone()[0]
	outbox = [json.loads(r["payload"])["text"] for r in conn.execute("SELECT payload FROM outbox").fetchall()]
	conn.close()

	assert status == "PROCESSED"
	assert any("RESPUESTA-FIJA" in t for t in outbox)


def test_e2e_run_once_wires_the_pulse_strategy(worker_env, monkeypatch):
	"""El enganche core→estrategia: run_once() DEBE invocar `_strategy.pulse(self)`.

	Sin este test, romper el enganche (p.ej. no llamar a la estrategia en
	run_once) pasaba desapercibido — la estrategia no procesa el inbox, así que
	los E2E de flujo no lo detectaban. Prueba por mutación: si run_once deja de
	llamar a pulse(), este test FALLA."""
	worker, _, _ = worker_env
	pulsed = []
	monkeypatch.setattr(type(worker._strategy), "pulse", lambda self, w: pulsed.append(w))

	worker.run_once()

	assert pulsed == [worker], "run_once debe invocar la estrategia de pulse exactamente una vez"
