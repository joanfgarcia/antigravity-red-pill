"""ARCH-001 paso B: the backend-specific pulse lives in a strategy, not the worker.

Fija el contrato de la separación:
- `IDEWorker` (core, neutro) ya NO expone los métodos Antigravity.
- `AntigravityPulseStrategy` (plugin) los expone todos.
- `NullPulseStrategy` satisface el protocolo `PulseStrategy`.
- `_build_strategy` devuelve la estrategia Antigravity (el import es el único
  punto que puede degradar a no-op).
"""

from __future__ import annotations

from types import SimpleNamespace

from red_pill.core.agent_worker import IDEWorker
from red_pill.core.pulse_strategy import NullPulseStrategy, PulseStrategy
from red_pill.plugins.antigravity_ide.pulse import AntigravityPulseStrategy
from red_pill.swarm.bridges import BackendType, BridgeCapabilities

_ANTIGRAVITY_METHODS = [
	"check_for_replies",
	"check_minion_inbox_auto_inject",
	"process_cognitive_queue",
	"check_minion_inbox_auto_inject_agy",
	"process_cognitive_queue_agy",
	"get_trajectory_data",
	"get_all_trajectories",
]


def test_worker_no_longer_exposes_antigravity_methods():
	for method in _ANTIGRAVITY_METHODS:
		assert not hasattr(IDEWorker, method), f"IDEWorker still exposes {method}"


def test_antigravity_strategy_exposes_all_moved_methods():
	for method in _ANTIGRAVITY_METHODS:
		assert hasattr(AntigravityPulseStrategy, method), f"strategy missing {method}"


def test_null_strategy_satisfies_protocol():
	assert isinstance(NullPulseStrategy(), PulseStrategy)


def test_antigravity_strategy_satisfies_protocol():
	assert isinstance(AntigravityPulseStrategy(None), PulseStrategy)


def test_build_strategy_returns_antigravity():
	worker = IDEWorker.__new__(IDEWorker)
	worker._bridge_minion = None
	strategy = worker._build_strategy()
	assert isinstance(strategy, AntigravityPulseStrategy)


def test_core_worker_is_backend_agnostic():
	"""El core NO debe importar ni instanciar Antigravity.

	Versión robusta (el grep de substrings original era un falso positivo
	demostrado por el panel: un `importlib` + `chr()` pasaba). Aquí se parsea el
	AST y se resuelven TODOS los imports de módulo — incluye aliases (`import x as
	y`, `from x import Y as Z`) y el nivel de módulo únicamente (los imports lazy
	dentro de funciones son el límite legítimo backend→core).
	"""
	import ast
	import inspect

	from red_pill.core import agent_worker as aw

	tree = ast.parse(inspect.getsource(aw))

	def _module_level_imports(node):
		for child in node.body:  # body top-level: excluye imports dentro de funciones
			if isinstance(child, ast.Import):
				for alias in child.names:
					yield alias.name
			elif isinstance(child, ast.ImportFrom):
				yield child.module or ""

	imports = list(_module_level_imports(tree))
	offenders = [m for m in imports if m and ("antigravity" in m.lower() or "ide_client" in m.lower())]
	assert not offenders, f"core/agent_worker no debe importar módulos de backend a nivel de módulo: {offenders}"


# ── Behavioral parity (BLOCKER del panel adversarial, 2026-10-01) ────────────
# El original tenía janitor + signal_samantha DENTRO del else (rama no-legacy).
# El refactor los había sacado a run_once (se ejecutaban siempre). Estos tests
# fijan la paridad: legacy gRPC = sin janitor/samantha; agy = con ellos.


def _instrumented_strategy(backend, monkeypatch, *, cascade_on, agy_on):
	calls: list[str] = []

	class _FakeTSM:
		def run_janitor_sweep(self):
			calls.append("janitor")
			return 0

	import red_pill.config as cfg
	import red_pill.telegram.session as tsm_mod

	monkeypatch.setattr(
		cfg,
		"get_config",
		lambda: SimpleNamespace(
			TELEGRAM_BRIDGE_CASCADE=[1] if cascade_on else [],
			AUTONOMOUS_AGY_ENABLED=agy_on,
		),
	)
	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", _FakeTSM)

	worker = IDEWorker.__new__(IDEWorker)
	worker._caps = BridgeCapabilities(backend=backend)
	worker._touch_lease = lambda: None
	worker._signal_samantha_worker = lambda: calls.append("samantha")

	strategy = AntigravityPulseStrategy(object(), client=SimpleNamespace())
	for name in (
		"check_for_replies",
		"check_minion_inbox_auto_inject",
		"process_cognitive_queue",
		"check_minion_inbox_auto_inject_agy",
		"process_cognitive_queue_agy",
	):
		monkeypatch.setattr(strategy, name, (lambda n: lambda *a, **k: calls.append(n))(name))
	return strategy, worker, calls


def test_parity_legacy_grpc_skips_janitor_and_samantha(monkeypatch):
	strategy, worker, calls = _instrumented_strategy(BackendType.GRPC, monkeypatch, cascade_on=False, agy_on=True)
	strategy.pulse(worker)
	assert calls == ["check_for_replies", "check_minion_inbox_auto_inject", "process_cognitive_queue"]
	assert "janitor" not in calls and "samantha" not in calls


def test_parity_agy_runs_janitor_and_samantha(monkeypatch):
	strategy, worker, calls = _instrumented_strategy(BackendType.OPENCODE, monkeypatch, cascade_on=False, agy_on=True)
	strategy.pulse(worker)
	assert calls == [
		"check_minion_inbox_auto_inject_agy",
		"process_cognitive_queue_agy",
		"janitor",
		"samantha",
	]


def test_parity_degraded_cascade_falls_to_agy_branch(monkeypatch):
	# legacy gRPC + TELEGRAM_BRIDGE_CASCADE configurada (cascade degradada) → el
	# original ponía legacy_grpc=False y caía al else: janitor + samantha SÍ.
	strategy, worker, calls = _instrumented_strategy(BackendType.GRPC, monkeypatch, cascade_on=True, agy_on=True)
	strategy.pulse(worker)
	assert calls == [
		"check_minion_inbox_auto_inject_agy",
		"process_cognitive_queue_agy",
		"janitor",
		"samantha",
	]


def test_check_for_replies_behavioral(monkeypatch, tmp_path):
	"""Conductual REAL de la lógica migrada (hueco 0% cobertura del panel).

	sqlite temporal + cliente mock: una cascade IDLE con un PlannerResponse de
	tipo 15 debe escribirse en `outbox` y marcarse PROCESSED. Si `check_for_replies`
	se vaciara a `pass`, este test FALLA (a diferencia de los de paridad)."""
	import sqlite3

	conn = sqlite3.connect(tmp_path / "events.db")
	conn.execute("CREATE TABLE inbox (message_id TEXT, channel TEXT, channel_user_id TEXT, payload TEXT, cascade_id TEXT, status TEXT)")
	conn.execute("CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, channel_user_id TEXT, cascade_id TEXT, payload TEXT)")
	conn.execute("INSERT INTO inbox (channel, channel_user_id, cascade_id, status) VALUES ('telegram', 'u1', 'cascade-1', 'WAITING_FOR_RESPONSE')")
	conn.commit()

	class FakeClient:
		def get_cascade_trajectory(self, cascade_id):
			return {
				"status": "CASCADE_RUN_STATUS_IDLE",
				"numTotalSteps": 1,
				"trajectory": {"steps": [{"type": "15", "plannerResponse": {"response": "hola mundo"}}]},
			}

	class FakeExtractor:
		def __init__(self, *a, **k):
			pass

		def get_latest_response(self, cascade_id):
			return None

	monkeypatch.setattr("red_pill.plugins.antigravity_ide.telegram_extractor.TelegramResponseExtractor", FakeExtractor)

	class FakeWorker:
		def _get_connection(self):
			return sqlite3.connect(tmp_path / "events.db")

	strategy = AntigravityPulseStrategy(object(), client=FakeClient())
	strategy.check_for_replies(FakeWorker())

	check = sqlite3.connect(tmp_path / "events.db")
	status = check.execute("SELECT status FROM inbox WHERE cascade_id='cascade-1'").fetchone()[0]
	out = check.execute("SELECT channel, payload FROM outbox").fetchall()
	assert status == "PROCESSED", "la respuesta IDLE debe marcar el inbox como PROCESSED"
	assert len(out) == 1 and "hola mundo" in out[0][1], "la respuesta debe escribirse en outbox"


def test_run_once_executes_with_null_strategy(monkeypatch):
	"""run_once() real con estrategia no-op: prueba que el pulse genérico no
	depende del backend y que la estrategia se invoca. (UNVERIFIABLE del panel.)"""
	pulsed = []
	worker = IDEWorker.__new__(IDEWorker)
	worker._touch_lease = lambda: None
	worker.process_inbox = lambda: None
	worker._check_telegram_jobs = lambda: None
	worker._watchdog_samantha = lambda: None
	worker.update_heartbeat = lambda: None
	worker._strategy = NullPulseStrategy()
	monkeypatch.setattr(NullPulseStrategy, "pulse", lambda self, w: pulsed.append(w))
	worker.run_once()
	assert pulsed == [worker]
