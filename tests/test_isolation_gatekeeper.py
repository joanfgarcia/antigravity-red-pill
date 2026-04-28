import os


def test_isolation_gatekeeper():
	"""Verify that MemoryManager defaults to :memory: in test environment."""
	from red_pill import config as cfg
	from red_pill.memory import MemoryManager

	# Both module-level alias and singleton instance must match
	assert cfg.QDRANT_URL == ":memory:"
	assert cfg.get_config().QDRANT_URL == ":memory:"

	mm = MemoryManager()
	# Ensure the memory manager initializes pointing to :memory:
	assert mm.storage.cfg.QDRANT_URL == ":memory:"


def test_config_isolation(bunker_isolation):
	"""Verify that IA_DIR is properly redirected via Pydantic singleton rebuild."""
	from red_pill import config as cfg

	# Validate singleton alignment with environment
	singleton_dir = cfg.get_config().IA_DIR
	module_dir = cfg.IA_DIR

	assert "bunker_test_" in singleton_dir, f"Pydantic singleton leaked: {singleton_dir}"
	assert "bunker_test_" in module_dir, f"Module alias leaked: {module_dir}"
	assert singleton_dir == module_dir, "Singleton and module alias drift detected in IA_DIR"

	# Validate isolation from host production paths
	prod_path = os.path.expanduser("~/Documents/IA/sharing")
	assert singleton_dir != prod_path
