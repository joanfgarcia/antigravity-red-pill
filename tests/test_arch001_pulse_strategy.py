"""ARCH-001 paso B: the backend-specific pulse lives in a strategy, not the worker.

Fija el contrato de la separación:
- `IDEWorker` (core, neutro) ya NO expone los métodos Antigravity.
- `AntigravityPulseStrategy` (plugin) los expone todos.
- `NullPulseStrategy` satisface el protocolo `PulseStrategy`.
- `_build_strategy` devuelve la estrategia Antigravity solo cuando algún puente
  la necesita (gRPC legacy o AUTONOMOUS_AGY_ENABLED); si no, la fábrica declina.
- El housekeeping genérico (janitor de sesiones Telegram + señal a Samantha)
  vive en el core y sobrevive a la ausencia del plugin.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from red_pill.core.agent_worker import IDEWorker
from red_pill.core.pulse_strategy import NullPulseStrategy, PulseContext, PulseStrategy, build_pulse_strategy
from red_pill.plugins.antigravity_ide.pulse import AntigravityPulseStrategy, build_antigravity_pulse_strategy
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


def _patch_cfg(monkeypatch, *, cascade_on=False, agy_on=False):
	import red_pill.config as cfg

	monkeypatch.setattr(
		cfg,
		"get_config",
		lambda: SimpleNamespace(
			TELEGRAM_BRIDGE_CASCADE=[SimpleNamespace(backend="opencode")] if cascade_on else [],
			AUTONOMOUS_AGY_ENABLED=agy_on,
		),
	)


@pytest.fixture
def no_ide_client(monkeypatch):
	"""The strategy builds its own IDE client (language-server discovery): stub it."""
	monkeypatch.setattr("red_pill.plugins.antigravity_ide.pulse.AntigravityIDEClient", MagicMock)


def test_worker_no_longer_exposes_antigravity_methods():
	for method in _ANTIGRAVITY_METHODS:
		assert not hasattr(IDEWorker, method), f"IDEWorker still exposes {method}"


def test_antigravity_strategy_exposes_all_moved_methods():
	for method in _ANTIGRAVITY_METHODS:
		assert hasattr(AntigravityPulseStrategy, method), f"strategy missing {method}"


def test_null_strategy_satisfies_protocol():
	assert isinstance(NullPulseStrategy(), PulseStrategy)


def test_antigravity_strategy_satisfies_protocol(no_ide_client):
	assert isinstance(AntigravityPulseStrategy(None), PulseStrategy)


def test_build_strategy_resolves_registered_backend(monkeypatch, no_ide_client):
	"""El core resuelve la estrategia por el registro (auto-descubrimiento del
	plugin), NO por un import directo. Con un puente gRPC legacy, la estrategia
	resultante es la del plugin — evidencia de que el registro funciona."""
	_patch_cfg(monkeypatch)
	worker = IDEWorker.__new__(IDEWorker)
	worker._bridge_minion = None
	worker._caps = BridgeCapabilities(backend=BackendType.GRPC)
	strategy = worker._build_strategy()
	assert isinstance(strategy, AntigravityPulseStrategy)


def test_build_strategy_declines_when_no_bridge_needs_antigravity(monkeypatch, no_ide_client):
	"""Config real de producción (opencode, AUTONOMOUS_AGY_ENABLED=False): la
	fábrica del plugin declina y el core usa el no-op — sin construir el cliente IDE."""
	_patch_cfg(monkeypatch, cascade_on=True, agy_on=False)
	worker = IDEWorker.__new__(IDEWorker)
	worker._bridge_minion = None
	worker._caps = BridgeCapabilities(backend=BackendType.OPENCODE, auto_approve=True)
	assert isinstance(worker._build_strategy(), NullPulseStrategy)


@pytest.mark.parametrize(
	("backend", "cascade_on", "agy_on", "applies"),
	[
		(BackendType.GRPC, False, False, True),  # legacy IDE polling
		(BackendType.GRPC, True, False, False),  # cascada degradada: nunca resucitar el polling
		(BackendType.OPENCODE, True, True, True),  # operaciones agy autónomas (opt-in)
		(BackendType.OPENCODE, True, False, False),  # producción: nada que hacer
		(None, False, False, False),  # sin puente construido
	],
)
def test_antigravity_factory_declines_unless_a_bridge_needs_it(monkeypatch, no_ide_client, backend, cascade_on, agy_on, applies):
	_patch_cfg(monkeypatch, cascade_on=cascade_on, agy_on=agy_on)
	caps = BridgeCapabilities(backend=backend) if backend else None
	strategy = build_antigravity_pulse_strategy(PulseContext(bridge_minion=None, capabilities=caps))
	assert isinstance(strategy, AntigravityPulseStrategy) is applies


def test_core_worker_is_backend_agnostic():
	"""El core NO debe importar NI NOMBRAR ningún backend/plugin concreto.

	Versión estricta (el grep de substrings era un falso positivo demostrado por
	el panel). Aquí se parsea el AST del módulo y se comprueba que NINGÚN import
	(a cualquier nivel) referencia un proveedor/plugin. Los backends se enganchan
	por el registro (`red_pill.core.pulse_strategy`), nunca importándose aquí.
	"""
	import ast
	import inspect

	from red_pill.core import agent_worker as aw

	tree = ast.parse(inspect.getsource(aw))
	_BACKEND_HINTS = ("antigravity", "ide_client", "agy_bridge", "grpc_bridge")

	offenders = []
	for node in ast.walk(tree):  # cualquier nivel, no solo módulo
		if isinstance(node, ast.Import):
			offenders += [a.name for a in node.names if any(h in a.name.lower() for h in _BACKEND_HINTS)]
		elif isinstance(node, ast.ImportFrom):
			mod = node.module or ""
			if any(h in mod.lower() for h in _BACKEND_HINTS):
				offenders.append(mod)

	assert not offenders, f"core/agent_worker no debe importar módulos de backend concreto: {offenders}"


def test_core_worker_strings_name_no_client_specific_tools():
	"""Los literales de texto del core (prompts incluidos) no nombran
	herramientas ni proveedores de un cliente concreto: el despertar corre en
	opencode pero el prompt hablaba de `run_command`/`write_to_file` y de
	`mcp_RedPill-Kernel_*` (nomenclatura de Antigravity)."""
	import ast
	import inspect
	import re

	from red_pill.core import agent_worker as aw

	forbidden = re.compile(
		r"run_command|write_to_file|replace_file_content|mcp_RedPill-Kernel_|mcp__|\b(antigravity|agy|grpc|opencode|claude)\b",
		re.IGNORECASE,
	)
	offenders = [
		node.value[:80]
		for node in ast.walk(ast.parse(inspect.getsource(aw)))
		if isinstance(node, ast.Constant) and isinstance(node.value, str) and forbidden.search(node.value)
	]
	assert not offenders, f"literales del core con nombres de cliente concreto: {offenders}"


def test_core_worker_has_no_transport_default():
	"""Hallazgo BAJA: el core no asume un transporte concreto (antes `_caps`
	nacía como gRPC). Ninguna referencia a BackendType en el worker neutro."""
	import inspect

	from red_pill.core import agent_worker as aw

	assert "BackendType" not in inspect.getsource(aw)


def test_pulse_strategy_registry_discovers_plugins(monkeypatch, no_ide_client):
	"""El registro descubre estrategias de plugins vía pkgutil, sin que el core
	los nombre. `build_pulse_strategy` devuelve la estrategia del plugin real."""
	_patch_cfg(monkeypatch)
	strategy = build_pulse_strategy(PulseContext(capabilities=BridgeCapabilities(backend=BackendType.GRPC)))
	assert type(strategy).__name__ != "NullPulseStrategy", "el registro debe descubrir la estrategia del plugin"


# ── Behavioral parity (BLOCKER del panel adversarial, 2026-10-01) ────────────
# El original tenía janitor + signal_samantha DENTRO del else (rama no-legacy).
# Ahora viven en el core (run_once) para sobrevivir sin plugin, y la rama legacy
# los declina explícitamente (`allows_core_housekeeping` → False). Estos tests
# recorren run_once real y fijan el orden: estrategia → janitor → samantha.


def _instrumented_worker(backend, monkeypatch, *, cascade_on, agy_on, strategy=None):
	calls: list[str] = []

	class _FakeTSM:
		def run_janitor_sweep(self):
			calls.append("janitor")
			return 0

	import red_pill.telegram.session as tsm_mod

	_patch_cfg(monkeypatch, cascade_on=cascade_on, agy_on=agy_on)
	monkeypatch.setattr(tsm_mod, "TelegramSessionManager", _FakeTSM)

	worker = IDEWorker.__new__(IDEWorker)
	worker._caps = BridgeCapabilities(backend=backend)
	worker._touch_lease = lambda: None
	worker.process_inbox = lambda: None
	worker._check_telegram_jobs = lambda: None
	worker._watchdog_samantha = lambda: None
	worker.update_heartbeat = lambda: None
	worker._signal_samantha_worker = lambda: calls.append("samantha")

	if strategy is None:
		strategy = AntigravityPulseStrategy(object(), client=SimpleNamespace())
		for name in (
			"check_for_replies",
			"check_minion_inbox_auto_inject",
			"process_cognitive_queue",
			"check_minion_inbox_auto_inject_agy",
			"process_cognitive_queue_agy",
		):
			monkeypatch.setattr(strategy, name, (lambda n: lambda *a, **k: calls.append(n))(name))
	worker._strategy = strategy
	return worker, calls


def test_parity_legacy_grpc_skips_janitor_and_samantha(monkeypatch):
	worker, calls = _instrumented_worker(BackendType.GRPC, monkeypatch, cascade_on=False, agy_on=True)
	worker.run_once()
	assert calls == ["check_for_replies", "check_minion_inbox_auto_inject", "process_cognitive_queue"]


def test_parity_agy_runs_janitor_and_samantha(monkeypatch):
	worker, calls = _instrumented_worker(BackendType.OPENCODE, monkeypatch, cascade_on=False, agy_on=True)
	worker.run_once()
	assert calls == [
		"check_minion_inbox_auto_inject_agy",
		"process_cognitive_queue_agy",
		"janitor",
		"samantha",
	]


def test_parity_degraded_cascade_falls_to_agy_branch(monkeypatch):
	# legacy gRPC + TELEGRAM_BRIDGE_CASCADE configurada (cascada degradada) → el
	# original ponía legacy_grpc=False y caía al else: janitor + samantha SÍ.
	worker, calls = _instrumented_worker(BackendType.GRPC, monkeypatch, cascade_on=True, agy_on=True)
	worker.run_once()
	assert calls == [
		"check_minion_inbox_auto_inject_agy",
		"process_cognitive_queue_agy",
		"janitor",
		"samantha",
	]


def test_housekeeping_survives_without_backend_plugin(monkeypatch):
	"""Regresión MEDIA: sin plugin (o con su import roto) la estrategia es la
	no-op, y el janitor de sesiones + la señal a Samantha SIGUEN corriendo."""
	worker, calls = _instrumented_worker(BackendType.OPENCODE, monkeypatch, cascade_on=True, agy_on=False, strategy=NullPulseStrategy())
	worker.run_once()
	assert calls == ["janitor", "samantha"]


def test_housekeeping_runs_if_strategy_flag_raises(monkeypatch):
	class _BrokenFlag(NullPulseStrategy):
		def allows_core_housekeeping(self, worker):
			raise RuntimeError("boom")

	worker, calls = _instrumented_worker(BackendType.OPENCODE, monkeypatch, cascade_on=True, agy_on=False, strategy=_BrokenFlag())
	worker.run_once()
	assert calls == ["janitor", "samantha"]


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
	worker._sweep_telegram_sessions = lambda: None
	worker._signal_samantha_worker = lambda: None
	worker._watchdog_samantha = lambda: None
	worker.update_heartbeat = lambda: None
	worker._strategy = NullPulseStrategy()
	monkeypatch.setattr(NullPulseStrategy, "pulse", lambda self, w: pulsed.append(w))
	worker.run_once()
	assert pulsed == [worker]


# ── Descubrimiento de plugins (hallazgos MEDIA: fallback silencioso + orden) ──


@pytest.fixture
def fake_plugins(tmp_path, monkeypatch, isolated_pulse_registry):
	"""Paquete `red_pill.plugins` apuntando a plugins falsos en tmp:
	- good/      pulse.py registra una fábrica.
	- broken/    pulse.py importa una dependencia inexistente (import transitivo).
	- nopulse/   sin pulse.py; su __init__ explota si alguien lo importa.
	- plain/     sin pulse.py, importable.
	"""
	import importlib
	import sys

	import red_pill.plugins as plugins_pkg

	root = tmp_path / "plugins"
	for name in ("good", "broken", "nopulse", "plain"):
		(root / name).mkdir(parents=True)
		(root / name / "__init__.py").write_text("")
	(root / "nopulse" / "__init__.py").write_text("raise RuntimeError('discovery must not import plugins without pulse')\n")
	(root / "good" / "pulse.py").write_text(
		"from red_pill.core.pulse_strategy import NullPulseStrategy, register_pulse_strategy\n"
		"class GoodStrategy(NullPulseStrategy):\n"
		"\tpass\n"
		"register_pulse_strategy(lambda context: GoodStrategy())\n"
	)
	(root / "broken" / "pulse.py").write_text("import definitely_missing_dependency_xyz  # noqa: F401\n")
	importlib.invalidate_caches()
	monkeypatch.setattr(plugins_pkg, "__path__", [str(root)])
	monkeypatch.setattr(isolated_pulse_registry, "_discovered", False)
	signals: list = []
	monkeypatch.setattr(isolated_pulse_registry, "_emit_strategy_fallback_signal", lambda module, error: signals.append((module, error)))
	yield isolated_pulse_registry, signals
	fake = {"good", "broken", "nopulse", "plain"}
	for mod in [m for m in sys.modules if m.startswith("red_pill.plugins.") and m.split(".")[2] in fake]:
		sys.modules.pop(mod, None)


def test_discovery_reports_transitive_import_failure(fake_plugins, caplog):
	"""Un pulse.py que existe pero no carga (dependencia transitiva ausente) ya
	no cae al no-op en silencio: logger.error + señal de dolor."""
	import logging
	import sys

	ps, signals = fake_plugins
	with caplog.at_level(logging.ERROR, logger="red_pill.core.pulse_strategy"):
		strategy = ps.build_pulse_strategy(PulseContext())

	assert type(strategy).__name__ == "GoodStrategy", "el plugin sano sigue registrándose"
	assert [module for module, _ in signals] == ["red_pill.plugins.broken.pulse"]
	assert "definitely_missing_dependency_xyz" in caplog.text
	assert "red_pill.plugins.nopulse" not in sys.modules, "un plugin sin pulse.py no se importa"


def test_discovery_quiet_when_pulse_module_itself_is_absent(fake_plugins, monkeypatch):
	"""Si no se puede mirar en disco y el import falla porque el propio pulse no
	existe, es la ausencia legítima: ni error ni señal."""
	import sys

	ps, signals = fake_plugins
	monkeypatch.setattr(ps, "_has_pulse_module", lambda importer, name: name != "nopulse")
	ps._discover_plugin_strategies()
	assert "red_pill.plugins.plain" in sys.modules, "sin mirar en disco, el import decide"
	assert [module for module, _ in signals] == ["red_pill.plugins.broken.pulse"], "plain (sin pulse) es silencioso"


def test_discovery_runs_once_regardless_of_prior_registrations(isolated_pulse_registry, monkeypatch):
	"""Antes el descubrimiento solo corría con el registro vacío: el primer
	registro explícito ocultaba para siempre los plugins. Ahora corre una vez."""
	ps = isolated_pulse_registry
	runs: list = []

	def _spy():
		runs.append(1)
		ps._discovered = True

	monkeypatch.setattr(ps, "_discovered", False)
	monkeypatch.setattr(ps, "_discover_plugin_strategies", _spy)
	ps.register_pulse_strategy(lambda context: None)
	ps.build_pulse_strategy(PulseContext())
	ps.build_pulse_strategy(PulseContext())
	assert runs == [1]


def test_strategy_fallback_signal_is_deduplicated(monkeypatch):
	import red_pill.core.pulse_strategy as ps
	import red_pill.memory as memory_mod

	injected: list = []

	class _FakeMM:
		active = False

		def has_signal(self, name):
			return _FakeMM.active

		def inject_signal(self, **kw):
			injected.append(kw)
			_FakeMM.active = True

	monkeypatch.setattr(memory_mod, "MemoryManager", _FakeMM)
	error = ModuleNotFoundError("No module named 'x'", name="x")
	ps._emit_strategy_fallback_signal("red_pill.plugins.antigravity_ide.pulse", error)
	ps._emit_strategy_fallback_signal("red_pill.plugins.antigravity_ide.pulse", error)
	assert len(injected) == 1
	assert injected[0]["name"] == "pulse_strategy_fallback_antigravity_ide"
	assert injected[0]["signal_type"] == "pain"
