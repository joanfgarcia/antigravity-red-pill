"""ARCH-001 — cobertura conductual de la lógica migrada en core/agent_worker.

El refactor movió ~400 líneas desde el plugin a `core/agent_worker.py` (y creó
`pulse_strategy.py`), bajando la cobertura total por debajo del umbral del CI
(80%). Estos tests ejercitan los caminos migrados que quedaron sin cubrir, con
DB real (tmp) — no mocks de dict.

Cubre: _build_strategy, _get_connection, _check_telegram_jobs (COMPLETED /
FRUSTRATED / dedup / sin destino), _process_awakening (budget agotado), _scribe_relay
(non-fatal), y el registro de pulse_strategy.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from red_pill.core.agent_worker import IDEWorker
from red_pill.core.pulse_strategy import (
	NullPulseStrategy,
	PulseStrategy,
	build_pulse_strategy,
	register_pulse_strategy,
)
from red_pill.swarm.bridges import BackendType, BridgeCapabilities


def _seed_events_db(db_path: Path) -> None:
	conn = sqlite3.connect(str(db_path))
	conn.executescript(
		"""
		CREATE TABLE inbox (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE,
			channel TEXT NOT NULL, channel_user_id TEXT NOT NULL, cascade_id TEXT,
			payload TEXT NOT NULL, status TEXT DEFAULT 'PENDING', retries INTEGER DEFAULT 0,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
		CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT,
			channel_user_id TEXT, cascade_id TEXT, payload TEXT);
		CREATE TABLE telegram_sessions (channel_user_id TEXT PRIMARY KEY, cascade_id TEXT,
			cascade_type TEXT, model TEXT, backend TEXT, accumulated_len INTEGER);
		CREATE TABLE cascade_mappings (id INTEGER PRIMARY KEY AUTOINCREMENT,
			channel_user_id TEXT, cascade_id TEXT, title TEXT);
		CREATE TABLE execution_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, exec_type TEXT,
			status TEXT, conversation_id TEXT, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			duration_s REAL, response_len INTEGER DEFAULT 0, counted INTEGER DEFAULT 1);
		CREATE TABLE system_health (service_name TEXT PRIMARY KEY, last_heartbeat TIMESTAMP);
		CREATE TABLE dead_letters (id INTEGER PRIMARY KEY AUTOINCREMENT, original_table TEXT,
			original_id INTEGER, channel TEXT, channel_user_id TEXT, payload TEXT, error_reason TEXT);
		"""
	)
	conn.commit()
	conn.close()


def _conn(db_path: Path):
	c = sqlite3.connect(str(db_path), timeout=10.0)
	c.row_factory = sqlite3.Row
	return c


@pytest.fixture
def worker(tmp_path, monkeypatch):
	db_path = tmp_path / "events.db"
	_seed_events_db(db_path)
	import red_pill.core.agent_worker as aw

	monkeypatch.setattr(aw, "DB_PATH", db_path)
	monkeypatch.setattr(aw, "get_connection", lambda: _conn(db_path))
	w = IDEWorker.__new__(IDEWorker)
	w._bridge_minion = None
	w._caps = BridgeCapabilities(backend=BackendType.OPENCODE, auto_approve=True)
	w.running = True
	return w, db_path


# ── pulse_strategy registry ─────────────────────────────────────────────────


def test_build_pulse_strategy_returns_registered():
	def factory(bridge):
		return NullPulseStrategy()

	register_pulse_strategy(factory)
	# Debe devolver la primera que aplique (la registrada o una descubierta).
	assert isinstance(build_pulse_strategy(None), PulseStrategy)


def test_build_pulse_strategy_falls_back_to_null(monkeypatch):
	import red_pill.core.pulse_strategy as ps

	monkeypatch.setattr(ps, "_STRATEGY_FACTORIES", [])
	monkeypatch.setattr(ps, "_discover_plugin_strategies", lambda: None)
	assert isinstance(build_pulse_strategy(None), NullPulseStrategy)


def test_factory_returning_none_is_skipped(monkeypatch):
	import red_pill.core.pulse_strategy as ps

	monkeypatch.setattr(ps, "_STRATEGY_FACTORIES", [])
	register_pulse_strategy(lambda bridge: None)
	monkeypatch.setattr(ps, "_discover_plugin_strategies", lambda: None)
	assert isinstance(build_pulse_strategy(None), NullPulseStrategy)


# ── worker helpers ──────────────────────────────────────────────────────────


def test_get_connection_returns_row_factory(worker):
	w, db_path = worker
	conn = w._get_connection()
	assert conn.row_factory is sqlite3.Row
	conn.close()


def test_build_strategy_uses_registry(worker):
	w, _ = worker
	strategy = w._build_strategy()
	assert isinstance(strategy, PulseStrategy)


# ── _check_telegram_jobs ────────────────────────────────────────────────────


class _FakeQueue:
	def __init__(self, jobs):
		self._jobs = jobs

	def list_tasks(self, **kw):
		return self._jobs

	def get_task(self, job_id):
		return self._jobs[0] if self._jobs else None

	def set_checkpoint_key(self, job_id, key, value):
		self._jobs[0].setdefault("checkpoint_data", {})[key] = value


def _job(status="COMPLETED", response="la respuesta", user="u1", delivered=False):
	return {
		"id": 1,
		"status": status,
		"error_log": "boom",
		"payload": {"telegram_channel_user_id": user, "telegram_chat_id": "telegram"},
		"checkpoint_data": {"response": response, "telegram_delivered": delivered},
	}


def _run_check(worker, job):
	w, db_path = worker
	with patch("red_pill.cognitive.queue_manager.CognitiveQueueManager", return_value=_FakeQueue([job])):
		w._check_telegram_jobs()
	conn = _conn(db_path)
	rows = [json.loads(r["payload"])["text"] for r in conn.execute("SELECT payload FROM outbox")]
	conn.close()
	return rows


def test_check_telegram_jobs_completed(worker):
	rows = _run_check(worker, _job(status="COMPLETED", response="todo bien"))
	assert rows == ["todo bien"]


def test_check_telegram_jobs_completed_empty_response(worker):
	rows = _run_check(worker, _job(status="COMPLETED", response=""))
	assert rows and "completada" in rows[0]


def test_check_telegram_jobs_frustrated(worker):
	rows = _run_check(worker, _job(status="FRUSTRATED"))
	assert rows and "falló" in rows[0]


def test_check_telegram_jobs_dedup_skips_delivered(worker):
	rows = _run_check(worker, _job(status="COMPLETED", delivered=True))
	assert rows == []


def test_check_telegram_jobs_no_destination_skipped(worker):
	rows = _run_check(worker, _job(status="COMPLETED", user=None))
	assert rows == []


# ── _process_awakening budget ───────────────────────────────────────────────


class _AwakeBridge:
	def __init__(self, response="informe del despertar", ok=True):
		self._r = response
		self._ok = ok

	def prompt(self, text, timeout=None, **kw):
		return type("R", (), {"ok": self._ok, "response": self._r, "error": "boom", "model": "m", "conversation_id": "c1"})()


def _seed_awake(worker, response="informe ok", ok=True):
	w, db_path = worker
	w._bridge_awakening = _AwakeBridge(response, ok)
	conn = _conn(db_path)
	conn.execute("INSERT INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES ('671868686','c1','local_session')")
	conn.execute("INSERT INTO inbox (message_id, channel, channel_user_id, payload, status) VALUES ('a2','system','sys','{}','PENDING')")
	conn.commit()
	m_id = conn.execute("SELECT id FROM inbox WHERE message_id='a2'").fetchone()[0]
	return conn, m_id


def test_process_awakening_full_path_routes_outbox(worker, monkeypatch):
	conn, m_id = _seed_awake(worker)
	w, db_path = worker
	cursor = conn.cursor()
	w._process_awakening("texto", [m_id], cursor, conn)
	conn.commit()
	out = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
	status = conn.execute("SELECT status FROM inbox WHERE id=?", (m_id,)).fetchone()[0]
	c = conn.execute("SELECT counted FROM execution_ledger ORDER BY id DESC LIMIT 1").fetchone()[0]
	conn.close()
	assert out == 1, "la respuesta del despertar debe ir al outbox"
	assert status == "PROCESSED"
	assert c == 1


def test_process_awakening_silence_does_not_count(worker, monkeypatch):
	conn, m_id = _seed_awake(worker, response="Ejercicio consciente del Derecho al Silencio: nada que reportar")
	w, db_path = worker
	cursor = conn.cursor()
	w._process_awakening("texto", [m_id], cursor, conn)
	conn.commit()
	c = conn.execute("SELECT counted FROM execution_ledger ORDER BY id DESC LIMIT 1").fetchone()[0]
	conn.close()
	assert c == 0, "el silencio no consume el tope (counted=0)"


def test_process_awakening_bridge_error(worker, monkeypatch):
	conn, m_id = _seed_awake(worker, ok=False)
	w, db_path = worker
	cursor = conn.cursor()
	w._process_awakening("texto", [m_id], cursor, conn)
	conn.commit()
	out = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
	conn.close()
	assert out == 0, "un fallo del bridge no debe emitir respuesta al outbox"


def test_process_awakening_budget_exhausted(worker, monkeypatch):
	w, db_path = worker
	# Llenar el ledger hasta el tope
	conn = _conn(db_path)
	for _ in range(8):
		conn.execute("INSERT INTO execution_ledger (exec_type, status, counted) VALUES ('awakening','started',1)")
	conn.execute("INSERT INTO inbox (message_id, channel, channel_user_id, payload, status) VALUES ('a1','system','sys','{}','PENDING')")
	conn.commit()
	msg_id = conn.execute("SELECT id FROM inbox WHERE message_id='a1'").fetchone()[0]
	cursor = conn.cursor()
	w._process_awakening("texto", [msg_id], cursor, conn)
	status = conn.execute("SELECT status FROM inbox WHERE id=?", (msg_id,)).fetchone()[0]
	conn.commit()
	conn.close()
	assert status == "PROCESSED", "budget agotado debe marcar PROCESSED y no procesar"


# ── _scribe_relay non-fatal ─────────────────────────────────────────────────


def test_scribe_relay_failure_is_non_fatal(worker, monkeypatch):
	w, _ = worker
	import red_pill.core.queue_manager as qm

	monkeypatch.setattr(qm, "MemoryQueueManager", MagicMock(side_effect=RuntimeError("no queue")))
	# No debe lanzar
	w._scribe_relay(user_prompt="p", agent_response="r")


def test_scribe_relay_enqueues(worker, monkeypatch):
	w, _ = worker
	import red_pill.core.queue_manager as qm

	fake = MagicMock()
	monkeypatch.setattr(qm, "MemoryQueueManager", lambda: fake)
	w._scribe_relay(user_prompt="p", agent_response="r", model="m", session_id="s")
	fake.enqueue_memory.assert_called_once()


# ── process_inbox: comandos de Telegram (caminos migrados) ───────────────────


def _enqueue_cmd(db_path, command, payload_extra=None):
	payload = {"text": f"/{command.lower()}", "command": command, "mode": "conversational"}
	if payload_extra:
		payload.update(payload_extra)
	conn = _conn(db_path)
	conn.execute(
		"INSERT INTO inbox (message_id, channel, channel_user_id, payload, status) VALUES (?,?,?,?,?)",
		(f"cmd_{command}", "telegram", "u1", json.dumps(payload), "PENDING"),
	)
	conn.commit()
	conn.close()


def _outbox_texts(db_path):
	conn = _conn(db_path)
	rows = [json.loads(r["payload"])["text"] for r in conn.execute("SELECT payload FROM outbox")]
	conn.close()
	return rows


def test_process_inbox_list_cascades(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.telegram.session as tsm_mod

	fake_tsm = MagicMock()
	fake_tsm.list_sessions.return_value = []
	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", lambda: fake_tsm)
	_enqueue_cmd(db_path, "LIST_CASCADES")
	w.process_inbox()
	texts = _outbox_texts(db_path)
	assert any("Sesiones" in t for t in texts)


def test_process_inbox_new_cascade(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.telegram.session as tsm_mod

	fake_tsm = MagicMock()
	fake_tsm.create_session.return_value = {"id": "sess-new"}
	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", lambda: fake_tsm)
	_enqueue_cmd(db_path, "NEW_CASCADE")
	w.process_inbox()
	conn = _conn(db_path)
	sess = conn.execute("SELECT cascade_id FROM telegram_sessions WHERE channel_user_id='u1'").fetchone()
	conn.close()
	assert sess is not None


def test_process_inbox_list_deferred_empty(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	_enqueue_cmd(db_path, "LIST_DEFERRED")
	w.process_inbox()
	assert any("DEFERRED" in t or "diferid" in t.lower() or "No hay" in t for t in _outbox_texts(db_path))


def test_process_inbox_show_model_no_session(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	_enqueue_cmd(db_path, "SHOW_MODEL")
	w.process_inbox()
	assert _outbox_texts(db_path), "un comando debe producir respuesta en outbox"


def test_handle_retry_failure_transient_cap(worker):
	w, db_path = worker
	conn = _conn(db_path)
	conn.execute("INSERT INTO inbox (message_id, channel, channel_user_id, payload, status, retries) VALUES ('r1','telegram','u1','{}','PENDING',0)")
	conn.commit()
	m_id = conn.execute("SELECT id FROM inbox WHERE message_id='r1'").fetchone()[0]
	cursor = conn.cursor()
	# transient: cap 3 → primera no mata
	killed = w._handle_retry_failure([m_id], "telegram", "u1", cursor, error_text="spawn error")
	assert killed is False
	conn.commit()
	conn.close()


def test_handle_retry_failure_timeout_cap_dead(worker):
	w, db_path = worker
	conn = _conn(db_path)
	conn.execute("INSERT INTO inbox (message_id, channel, channel_user_id, payload, status, retries) VALUES ('r2','telegram','u1','{}','PENDING',2)")
	conn.commit()
	m_id = conn.execute("SELECT id FROM inbox WHERE message_id='r2'").fetchone()[0]
	cursor = conn.cursor()
	killed = w._handle_retry_failure([m_id], "telegram", "u1", cursor, error_text="bridge timed out")
	conn.commit()
	status = conn.execute("SELECT status FROM inbox WHERE id=?", (m_id,)).fetchone()[0]
	outbox = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
	conn.close()
	assert killed is True
	assert status == "DEAD"
	assert outbox == 1


def test_update_heartbeat(worker):
	w, db_path = worker
	conn = _conn(db_path)
	conn.execute("INSERT INTO system_health (service_name) VALUES ('red_pill')")
	conn.commit()
	conn.close()
	w.update_heartbeat()
	conn = _conn(db_path)
	hb = conn.execute("SELECT last_heartbeat FROM system_health WHERE service_name='red_pill'").fetchone()[0]
	conn.close()
	assert hb is not None


def test_session_cascade_specs_empty(worker):
	w, db_path = worker
	conn = _conn(db_path)
	cursor = conn.cursor()
	specs = w._session_cascade_specs("u1", cursor)
	conn.close()
	assert isinstance(specs, list)


def test_watchdog_samantha_without_worker(worker):
	w, _ = worker
	w._samantha_worker = None
	# No debe lanzar ni intentar reiniciar
	w._watchdog_samantha()


def test_process_inbox_list_models(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.core.model_catalog as mc

	catalog = MagicMock()
	catalog.models.return_value = [{"id": "m1", "tier": "pro", "priority": 1, "roles": ["chat"]}]
	monkeypatch.setattr(mc, "ModelCatalog", lambda: catalog)
	_enqueue_cmd(db_path, "LIST_MODELS")
	w.process_inbox()
	assert any("Modelos" in t or "m1" in t for t in _outbox_texts(db_path))


def test_process_inbox_list_models_empty(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.core.model_catalog as mc

	catalog = MagicMock()
	catalog.models.return_value = []
	monkeypatch.setattr(mc, "ModelCatalog", lambda: catalog)
	_enqueue_cmd(db_path, "LIST_MODELS")
	w.process_inbox()
	assert any("No hay" in t for t in _outbox_texts(db_path))


def test_process_inbox_list_models_error(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.core.model_catalog as mc

	monkeypatch.setattr(mc, "ModelCatalog", MagicMock(side_effect=RuntimeError("no cat")))
	_enqueue_cmd(db_path, "LIST_MODELS")
	w.process_inbox()
	assert any("catálogo" in t for t in _outbox_texts(db_path))


def test_process_inbox_show_queue_empty(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.cognitive.queue_manager as qm

	fake = MagicMock()
	fake.list_tasks.return_value = []
	monkeypatch.setattr(qm, "CognitiveQueueManager", lambda: fake)
	_enqueue_cmd(db_path, "SHOW_QUEUE")
	w.process_inbox()
	assert any("vacía" in t or "cola" in t.lower() for t in _outbox_texts(db_path))


def test_process_inbox_show_queue_with_tasks(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.cognitive.queue_manager as qm

	fake = MagicMock()
	fake.list_tasks.return_value = [{"id": "abcdef123", "status": "PENDING", "priority": 5, "title": "tarea"}]
	monkeypatch.setattr(qm, "CognitiveQueueManager", lambda: fake)
	_enqueue_cmd(db_path, "SHOW_QUEUE")
	w.process_inbox()
	assert any("PENDING" in t for t in _outbox_texts(db_path))


def test_process_inbox_show_queue_error(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.cognitive.queue_manager as qm

	monkeypatch.setattr(qm, "CognitiveQueueManager", MagicMock(side_effect=RuntimeError("no queue")))
	_enqueue_cmd(db_path, "SHOW_QUEUE")
	w.process_inbox()
	assert any("cola" in t.lower() for t in _outbox_texts(db_path))


def test_process_via_bridge_cascade_exhausted_defers(worker, monkeypatch):
	w, db_path = worker
	import red_pill.telegram.session as tsm_mod
	from red_pill.swarm.bridges import NoModelsConfigured

	class _Sess:
		def __init__(self, *a, **k):
			pass

		def get_session(self, sid):
			return {"id": sid, "status": "active", "steps": []}

		def create_session(self, uid):
			return {"id": "s1", "status": "active", "steps": []}

		def append_message(self, *a, **k):
			pass

		def trigger_compaction(self, *a, **k):
			return None

	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", _Sess)

	class _ExhaustedBridge:
		def prompt(self, *a, **k):
			raise NoModelsConfigured("no quotas left")

	w._bridge_telegram = _ExhaustedBridge()
	conn = w._get_connection()
	cursor = conn.cursor()
	w._process_via_bridge("hola", [1], "telegram", "u1", cursor, conn)
	conn.commit()
	rows = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
	conn.close()
	assert rows == 1, "la cascade exhausta debe dejar aviso DEFERRED en outbox"


def test_process_via_bridge_generic_error_retries(worker, monkeypatch):
	w, db_path = worker
	import red_pill.telegram.session as tsm_mod

	class _Sess:
		def __init__(self, *a, **k):
			pass

		def get_session(self, sid):
			return {"id": sid, "status": "active", "steps": []}

		def create_session(self, uid):
			return {"id": "s1", "status": "active", "steps": []}

		def append_message(self, *a, **k):
			pass

		def trigger_compaction(self, *a, **k):
			return None

	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", _Sess)

	class _BoomBridge:
		def prompt(self, *a, **k):
			raise RuntimeError("boom")

	retried = {}

	def _fake_retry(*a, **k):
		retried["hit"] = True
		return False

	w._handle_retry_failure = _fake_retry
	w._bridge_telegram = _BoomBridge()
	conn = w._get_connection()
	cursor = conn.cursor()
	w._process_via_bridge("hola", [1], "telegram", "u1", cursor, conn)
	conn.close()
	assert retried.get("hit"), "un error del bridge debe pasar por _handle_retry_failure"


def test_enqueue_heavy_path_empty_text_dead(worker, monkeypatch):
	w, db_path = worker
	conn = _conn(db_path)
	conn.execute("INSERT INTO inbox (message_id, channel, channel_user_id, payload, status) VALUES ('h1','telegram','u1','{}','PENDING')")
	conn.commit()
	m_id = conn.execute("SELECT id FROM inbox WHERE message_id='h1'").fetchone()[0]
	cursor = conn.cursor()
	w._enqueue_heavy_path("", "telegram", "u1", [m_id], cursor, conn)
	check = _conn(db_path)
	status = check.execute("SELECT status FROM inbox WHERE id=?", (m_id,)).fetchone()[0]
	check.close()
	assert status == "DEAD"


def test_enqueue_heavy_path_normal(worker, monkeypatch):
	w, db_path = worker
	import red_pill.cognitive.queue_manager as qm
	import red_pill.telegram.session as tsm_mod

	fake_q = MagicMock()
	monkeypatch.setattr(qm, "CognitiveQueueManager", lambda: fake_q)
	fake_tsm = MagicMock()
	fake_tsm.create_session.return_value = {"id": "s1"}
	fake_tsm.get_session.return_value = {"id": "s1", "steps": []}
	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", lambda: fake_tsm)
	monkeypatch.setattr(w, "_session_cascade_specs", lambda *a, **k: [])

	conn = _conn(db_path)
	conn.execute("INSERT INTO inbox (message_id, channel, channel_user_id, payload, status) VALUES ('h2','telegram','u1','{}','PENDING')")
	conn.commit()
	m_id = conn.execute("SELECT id FROM inbox WHERE message_id='h2'").fetchone()[0]
	cursor = conn.cursor()
	w._enqueue_heavy_path("tarea larga", "telegram", "u1", [m_id], cursor, conn)
	enq = fake_q.enqueue_task.called
	check = _conn(db_path)
	outbox = check.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
	check.close()
	assert enq, "debe encolar el agentic_job"
	assert outbox == 1, "debe acusar '⏳ en cola'"


def test_run_loop_stops_after_one_tick(worker, monkeypatch):
	w, _ = worker
	ticks = {"n": 0}

	def _once():
		ticks["n"] += 1
		w.running = False

	monkeypatch.setattr(w, "run_once", _once)
	w.run()
	assert ticks["n"] == 1


def test_run_loop_contains_exception(worker, monkeypatch):
	w, _ = worker
	state = {"n": 0}

	def _boom():
		state["n"] += 1
		w.running = False
		raise RuntimeError("pulse blew up")

	monkeypatch.setattr(w, "run_once", _boom)
	w.run()  # no debe propagar
	assert state["n"] == 1


def test_process_inbox_set_model_unknown(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	_enqueue_cmd(db_path, "SET_MODEL", {"model": "no-existe-xyz"})
	w.process_inbox()
	assert any("catálogo" in t or "no está" in t for t in _outbox_texts(db_path))


def test_process_inbox_list_deferred_with_rows(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	conn = _conn(db_path)
	# un mensaje previo ya diferido (para que el comando tenga algo que listar)
	conn.execute(
		"INSERT INTO inbox (message_id, channel, channel_user_id, payload, status, retries) VALUES ('old1','telegram','u1',?, 'DEFERRED', 1)",
		(json.dumps({"text": "hola"}),),
	)
	conn.commit()
	conn.close()
	# el comando en sí entra como PENDING
	_enqueue_cmd(db_path, "LIST_DEFERRED")
	w.process_inbox()
	assert any("DEFERRED" in t for t in _outbox_texts(db_path))


def _call_via_bridge(w, monkeypatch, msg="hola", bridge=None, escalate=False):
	"""Invoca _process_via_bridge con una sesión limpia y bridge controlable."""
	import red_pill.telegram.session as tsm_mod

	class _FakeSession:
		def __init__(self, *a, **k):
			pass

		def get_session(self, sid):
			return {"id": sid, "status": "active", "steps": []}

		def create_session(self, uid):
			return {"id": "s1", "status": "active", "steps": []}

		def append_message(self, *a, **k):
			pass

		def trigger_compaction(self, *a, **k):
			return None

	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", _FakeSession)

	class _Bridge:
		def prompt(self, text, timeout=None, **kw):
			resp = "[ESCALATE]" if escalate else "respuesta"
			return type("R", (), {"ok": True, "response": resp, "model": "m", "error": None})()

	w._bridge_telegram = bridge if bridge is not None else _Bridge()
	conn = w._get_connection()
	cursor = conn.cursor()
	w._process_via_bridge(msg, [1], "telegram", "u1", cursor, conn)
	conn.commit()
	conn.close()


def test_process_via_bridge_routing_keyword_goes_heavy(worker, monkeypatch):
	w, db_path = worker
	enqueued = {}
	monkeypatch.setattr(w, "_enqueue_heavy_path", lambda **kw: enqueued.update(kw))
	_call_via_bridge(w, monkeypatch, msg="/mission haz algo")
	assert "text" in enqueued, "el keyword de routing debe desviar al heavy path"


def test_process_via_bridge_no_bridge_records_failure(worker, monkeypatch):
	w, db_path = worker
	calls = {}

	def _fake(*a, **k):
		calls.update(k)
		return True

	monkeypatch.setattr(w, "_handle_retry_failure", _fake)
	_call_via_bridge(w, monkeypatch, bridge=False)
	assert calls.get("error_text") == "no bridge available"


def test_process_via_bridge_escalate_enqueues_heavy(worker, monkeypatch):
	w, db_path = worker
	enqueued = {}
	monkeypatch.setattr(w, "_enqueue_heavy_path", lambda **kw: enqueued.update(kw))
	_call_via_bridge(w, monkeypatch, escalate=True)
	assert "text" in enqueued, "[ESCALATE] del modelo debe desviar al heavy path"


def test_process_inbox_background_message(worker, monkeypatch):
	w, db_path = worker
	w._bridge_telegram = MagicMock()
	import red_pill.core.inbox as inbox_mod

	fake_minion = MagicMock()
	monkeypatch.setattr(inbox_mod, "MinionInbox", lambda: fake_minion)
	conn = _conn(db_path)
	conn.execute(
		"INSERT INTO inbox (message_id, channel, channel_user_id, payload, status) VALUES (?,?,?,?,?)",
		("bg1", "telegram", "u1", json.dumps({"text": "nota", "mode": "background"}), "PENDING"),
	)
	conn.commit()
	conn.close()
	w.process_inbox()
	conn = _conn(db_path)
	status = conn.execute("SELECT status FROM inbox WHERE message_id='bg1'").fetchone()[0]
	conn.close()
	assert status == "DELIVERED_BACKGROUND"
