"""
conftest.py — Session-scope stubs to prevent live ML model downloads
and hardware probes during unit tests.

CERT-COND: All tests must be runnable without network access or GPU hardware.
"""

import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


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
	"""Apply a default timeout to all tests that don't already have one."""
	try:
		import importlib.util

		if not importlib.util.find_spec("pytest_timeout"):
			raise ImportError

		for item in items:
			if item.get_closest_marker("timeout") is None:
				item.add_marker(pytest.mark.timeout(30))
	except ImportError:
		pass


def check_qdrant_running():
	import socket

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
		s.settimeout(0.5)
		return s.connect_ex(("localhost", 6333)) == 0


def pytest_runtest_setup(item):
	if "integration" in item.keywords and not check_qdrant_running():
		pytest.skip("TEST-002: Integration tests require Qdrant (Docker) running on port 6333.")
