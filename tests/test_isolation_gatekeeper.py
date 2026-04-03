import os

from red_pill import config as cfg
from red_pill.memory import MemoryManager


def test_isolation_gatekeeper():
    """Verify that MemoryManager defaults to :memory: in test environment."""
    from red_pill import config as cfg
    assert cfg.QDRANT_URL == ":memory:"
    mm = MemoryManager()
    # If it didn't raise, it's using :memory: (since 6333 is blocked in conftest)
    assert mm.storage.cfg.QDRANT_URL == ":memory:"

def test_config_isolation(bunker_isolation):
    """Verify that IA_DIR is redirected to a temporary path."""
    assert "bunker_test_" in cfg.IA_DIR
    assert cfg.IA_DIR != os.path.expanduser("~/Documents/IA/sharing")
