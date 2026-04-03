import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# v6.3.7: Secure Isolation Gatekeeper
# Force :memory: location for all unit tests to prevent production leakage.
os.environ["QDRANT_HOST"] = ":memory:"
os.environ["QDRANT_PORT"] = "0"
os.environ["IA_DIR"] = tempfile.gettempdir()  # Redirect all storage to /tmp

@pytest.fixture(autouse=True)
def bunker_isolation(monkeypatch):
	"""
	Universal isolation fixture (AUTO-USE).
	Ensures that no test accidentallly hits the production Qdrant or filesystem.
	"""
	from red_pill import config as cfg

	# Force isolated testing paths
	test_dir = tempfile.mkdtemp(prefix="bunker_test_")
	monkeypatch.setattr(cfg, "IA_DIR", test_dir)

	# Force Qdrant into memory mode UNLESS explicitly requested via integration marker
	# NOTE: This overrides the module-level lazy attributes
	monkeypatch.setattr(cfg, "QDRANT_URL", ":memory:")

	yield test_dir


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


def check_qdrant_running(port=6333):
	import socket

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
		s.settimeout(0.5)
		return s.connect_ex(("localhost", port)) == 0


def pytest_runtest_setup(item):
	# PROTECT BÜNKER: Prevent running integration tests against production port (6333)
	if "integration" in item.keywords:
		if os.getenv("ALLOW_PRODUCTION_TESTING") != "true":
			pytest.skip("SEC-TEST-001: Integration tests are BLOCKED from production port 6333 to prevent engram corruption. Use a dedicated test instance.")
