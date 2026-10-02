import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import _isolation_guards as _guards  # vive junto a este conftest
import pytest

# GUARDAS DE AISLAMIENTO (antes que nada): sandbox temporal propio de la sesión,
# red sin servicios reales del operador y comandos de host emulados. Detalle y
# opt-out (`@pytest.mark.allow_local_services`) en tests/_isolation_guards.py.
_SANDBOX, _SANDBOX_OWNED = _guards.setup_sandbox()
_guards.install()

# Nada de red ni GPU por la puerta de atrás: modelos de HF solo desde caché y
# CUDA invisible (la suite no necesita ni una cosa ni la otra).
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# v6.3.7: Secure Isolation Gatekeeper
# Force :memory: location for all unit tests to prevent production leakage.
os.environ["QDRANT_HOST"] = ":memory:"
os.environ["QDRANT_PORT"] = "0"
os.environ["APP_ROOT"] = tempfile.gettempdir()  # Redirect all storage to the sandbox

# TEST ISOLATION (module level, BEFORE any red_pill import in collection):
# redirect every operator location to a tmp dir AND arm the production-write
# guard, so that even module-import-time code cannot touch the operator's real
# storage. The fixture below re-applies per-test dirs on top of this.
# - XDG_CONFIG_HOME: importing agent_worker/config loads `<config>/.env`; with the
#   real one, AGENT_CORE_DIR / NEON_LINK_DB_PATH / cascades leaked into the suite.
# - XDG_STATE_HOME: get_log_dir().
# - AGENT_CORE_DIR: the operator's desk (awakening notes and logs).
# - IA_DIR: the bunker root (bunker_export wrote kits into the live repo).
# - XDG_RUNTIME_DIR: /run/user/<uid> (gpu_reservations.json of a live GPU job,
#   bunker_state.json). It must EXIST: RUNTIME_DIR falls back past a missing one.
_TEST_ISOLATION_DIR = tempfile.mkdtemp(prefix="redpill_test_iso_")


def _isolated_locations(base: str) -> dict:
	return {
		"XDG_DATA_HOME": os.path.join(base, "data"),
		"XDG_CACHE_HOME": os.path.join(base, "cache"),
		"XDG_CONFIG_HOME": os.path.join(base, "config"),
		"XDG_STATE_HOME": os.path.join(base, "state"),
		"XDG_RUNTIME_DIR": os.path.join(base, "runtime"),
		"AGENT_CORE_DIR": os.path.join(base, "desk"),
		"IA_DIR": os.path.join(base, "ia", "sharing"),
	}


def _make_runtime_dir(locations: dict) -> None:
	os.makedirs(locations["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)


_SESSION_LOCATIONS = _isolated_locations(_TEST_ISOLATION_DIR)
_make_runtime_dir(_SESSION_LOCATIONS)
os.environ.update(_SESSION_LOCATIONS)
# An operator shell that exported its .env must not aim the worker at the real events.db.
os.environ.pop("NEON_LINK_DB_PATH", None)
os.environ["REDPILL_TESTING"] = "1"


@pytest.fixture(autouse=True)
def _isolation_guards(request):
	"""Falla el test si ha intentado tocar un servicio vivo del operador (red o
	systemctl/podman mutante), aunque el código se tragase el error. Opt-out:
	`@pytest.mark.allow_local_services`; los `integration` solo con
	ALLOW_PRODUCTION_TESTING=true (si no, ya se saltan)."""
	allowed = request.node.get_closest_marker("allow_local_services") is not None
	if "integration" in request.node.keywords and os.getenv("ALLOW_PRODUCTION_TESTING") == "true":
		allowed = True
	with _guards.bypass(allowed):
		yield
	violations = _guards.take_violations()
	if violations:
		pytest.fail(
			"[TEST ISOLATION] el test intentó tocar servicios reales del operador (bloqueado):\n  " + "\n  ".join(violations),
			pytrace=False,
		)


_SW_FLAGS = (
	"SW_AFFINITY_ENABLED",
	"SW_PURGE_GATE_ENABLED",
	"SW_DEDUP_ENABLED",
	"SW_HUBS_ENABLED",
	"SW_THREAD_ENABLED",
	"SW_ABSENCE_GUARD_CONDITIONAL",
	"SW_EROSION_DEMOTE_ENABLED",
	"SW_SITUATION_ENABLED",
	"SW_INTERACTIVE_PHASE_ENABLED",
	"MEMENTO_REALTIME_TAG_ENABLED",
)


@pytest.fixture(autouse=True)
def _default_ingest_not_retired(monkeypatch):
	"""Hermético a los flags single-writer/RFC-004: la suite corre con el default
	de fábrica (OFF) aunque el `.env` del operador los tenga ON. Los tests que
	necesitan un flag lo activan con monkeypatch en su cuerpo (gana al fixture)."""
	import red_pill.config as _cfg

	for name in _SW_FLAGS:
		if hasattr(_cfg, name):
			monkeypatch.setattr(_cfg, name, False)


@pytest.fixture(autouse=True)
def bunker_isolation(monkeypatch):
	"""
	Universal isolation fixture (AUTO-USE).
	Ensures that no test accidentally hits the production Qdrant or filesystem.
	"""
	from unittest.mock import MagicMock

	from red_pill.config import get_config
	from red_pill.core.providers import BaseInferenceProvider, BaseTelemetryProvider, ProviderRegistry

	# 1. Clear the singleton cache so the next get_config() rebuilds with new envs
	get_config.cache_clear()

	# 1.5. Isolate ProviderRegistry and provide defaults to avoid "No inference provider" errors
	ProviderRegistry.reset()
	mock_inference = MagicMock(spec=BaseInferenceProvider)
	mock_inference.generate.return_value = '{"summary": "test", "emotion": "neutral", "intensity": 0.5}'
	ProviderRegistry.register_inference_provider("sip", mock_inference, default=True)
	ProviderRegistry.register_telemetry_provider(MagicMock(spec=BaseTelemetryProvider))

	# 2. Force isolated testing paths via environment (inside the session sandbox,
	# which the owning process removes at the end: no more bunker_test_* in /tmp)
	test_dir = tempfile.mkdtemp(prefix="bunker_test_")
	monkeypatch.setenv("APP_ROOT", test_dir)
	monkeypatch.setenv("WORKSPACE_ROOT", test_dir)
	locations = _isolated_locations(test_dir)
	_make_runtime_dir(locations)
	for name, value in locations.items():
		monkeypatch.setenv(name, value)
	monkeypatch.delenv("NEON_LINK_DB_PATH", raising=False)
	# Explicit isolation flag: paths.py aborts if a test resolves to the real
	# production data dir (defence in depth beyond the env redirect above).
	monkeypatch.setenv("REDPILL_TESTING", "1")

	# 3. Force Qdrant into memory mode via env variables for Pydantic to capture
	monkeypatch.setenv("QDRANT_HOST", ":memory:")
	monkeypatch.setenv("QDRANT_URL", ":memory:")

	# Force rebuild for this test immediately
	get_config()

	yield test_dir

	# 4. Clean cache after test finishes
	get_config.cache_clear()


@pytest.fixture(autouse=True)
def _no_live_engine_probe(monkeypatch):
	"""memento.agentic.engine_id() pregunta al daemon REAL (GET :8760/v1/models) y
	cachea por proceso: el primer test de cada worker que destilaba lo tocaba. La
	suite arranca con la caché ya puesta al modelo por defecto (el test del probe
	la vacía él mismo y mockea urlopen)."""
	import red_pill.memento.agentic.runtime as engine_runtime

	monkeypatch.setattr(engine_runtime, "_ENGINE_CACHE", engine_runtime.EDGE_MODEL)


@pytest.fixture
def isolated_pulse_registry(monkeypatch):
	"""Empty pulse-strategy registry for one test, restored afterwards.

	Plugin discovery registers factories as an import side effect, once per
	process: run the real discovery BEFORE swapping the registry so a plugin's
	first import never lands in (and dies with) the test's temporary list."""
	import red_pill.core.pulse_strategy as ps

	if not ps._discovered:
		ps._discover_plugin_strategies()
	monkeypatch.setattr(ps, "_STRATEGY_FACTORIES", [])
	monkeypatch.setattr(ps, "_discovered", True)
	return ps


@pytest.fixture
def memory_manager():
	"""Provides a clean, memory-based MemoryManager for each test."""
	from red_pill.memory import MemoryManager

	mm = MemoryManager(url=":memory:")
	# Mock metabolism to prevent background noise
	mm.metabolism = MagicMock()
	return mm


@pytest.fixture
def short_socket_dir():
	"""Provides a short temporary directory path suitable for macOS AF_UNIX sockets (<104 chars)."""
	with tempfile.TemporaryDirectory(prefix="rpm_") as d:
		yield Path(d)


def _stub_fastembed():
	"""Inject a minimal fastembed stub into sys.modules before any test import."""
	if "fastembed" not in sys.modules:
		fake = types.ModuleType("fastembed")
		mock_emb_cls = MagicMock()

		def mock_embed(texts, **kwargs):
			return (MagicMock(tolist=lambda: [0.1] * 384) for _ in texts)

		mock_emb_cls.return_value.embed.side_effect = mock_embed
		fake.TextEmbedding = mock_emb_cls  # type: ignore
		sys.modules["fastembed"] = fake


_stub_fastembed()


def pytest_collection_modifyitems(items):
	"""Apply a default timeout and categorize integration tests."""
	try:
		import importlib.util

		if not importlib.util.find_spec("pytest_timeout"):
			raise ImportError

		for item in items:
			if item.get_closest_marker("timeout") is None:
				item.add_marker(pytest.mark.timeout(30))
	except ImportError:
		pass


def pytest_configure(config):
	config.addinivalue_line(
		"markers",
		"allow_local_services: desactiva las guardas de red/comandos de host para un test que habla A PROPÓSITO con un servicio local",
	)
	# Un --basetemp explícito fuera del sandbox también es terreno de los tests.
	if config.option.basetemp:
		_guards.allow_unix_root(str(config.option.basetemp))


def pytest_unconfigure(config):
	# Solo el proceso que creó el sandbox lo borra (los workers de xdist lo heredan).
	if _SANDBOX_OWNED:
		_guards.remove_sandbox(_SANDBOX)


def pytest_runtest_setup(item):
	# PROTECT BÜNKER: Prevent running integration tests against production port (6333)
	if "integration" in item.keywords:
		if os.getenv("ALLOW_PRODUCTION_TESTING") != "true":
			pytest.skip(
				"SEC-TEST-001: Integration tests are BLOCKED from production port 6333 to prevent engram corruption. Use a dedicated test instance."
			)
