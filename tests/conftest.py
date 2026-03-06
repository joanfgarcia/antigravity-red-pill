"""
conftest.py — Session-scope stubs to prevent live ML model downloads
and hardware probes during unit tests.

CERT-COND: All tests must be runnable without network access or GPU hardware.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest
from pathlib import Path
import tempfile

@pytest.fixture
def short_socket_dir():
	"""Provides a short temporary directory path suitable for macOS AF_UNIX sockets (<104 chars)."""
	with tempfile.TemporaryDirectory(prefix="rpm_") as d:
		yield Path(d)


# ─────────────────────────────────────────────────────────────────────────────
# Block fastembed (TextEmbedding) from downloading real models
# ─────────────────────────────────────────────────────────────────────────────

def _stub_fastembed():
    """Inject a minimal fastembed stub into sys.modules before any test import."""
    if "fastembed" not in sys.modules:
        fake = types.ModuleType("fastembed")
        mock_emb_cls = MagicMock()
        # embed() returns an iterator of mock vectors
        mock_emb_cls.return_value.embed.return_value = iter([MagicMock(tolist=lambda: [0.0] * 384)])
        fake.TextEmbedding = mock_emb_cls
        sys.modules["fastembed"] = fake


_stub_fastembed()


# ─────────────────────────────────────────────────────────────────────────────
# Pytest timeout guard: mark any test running >30s as failed
# ─────────────────────────────────────────────────────────────────────────────

def pytest_collection_modifyitems(items):
    """Apply a default timeout to all tests that don't already have one."""
    try:
        import pytest_timeout  # noqa: F401
        for item in items:
            if item.get_closest_marker("timeout") is None:
                item.add_marker(pytest.mark.timeout(30))
    except ImportError:
        pass  # pytest-timeout not installed; skip
