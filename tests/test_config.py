"""Tests for config.py — targeting lines 18-20, 42-44, 85, 87, 223.
These lines execute at module import time based on env vars.
We test them by importing config in a subprocess-like manner via importlib.
"""

import importlib
import os
import sys
import warnings

import pytest


def _reimport_config(env_overrides: dict):
	"""Re-import red_pill.config with custom environment variables."""
	original_env = {}
	for key in env_overrides:
		original_env[key] = os.environ.get(key)
		os.environ[key] = env_overrides[key]
	mod_name = "red_pill.config"
	cached = sys.modules.get(mod_name)
	if mod_name in sys.modules:
		del sys.modules[mod_name]
	try:
		mod = importlib.import_module(mod_name)
		return mod
	finally:
		for key, val in original_env.items():
			if val is None:
				os.environ.pop(key, None)
			else:
				os.environ[key] = val
		if cached is not None:
			sys.modules[mod_name] = cached
		elif mod_name in sys.modules:
			del sys.modules[mod_name]


class TestConfigWarnings:
	def test_qdrant_http_non_local_warns(self):
		"""Lines 18-20: QDRANT_SCHEME=http + non-local host → UserWarning emitted."""
		with warnings.catch_warnings(record=True) as w:
			warnings.simplefilter("always")
			_reimport_config({"QDRANT_SCHEME": "http", "QDRANT_HOST": "remote.example.com", "MILVUS_ENABLED": "False"})
		sec_warnings = [x for x in w if "SEC-F04" in str(x.message) or "cleartext" in str(x.message).lower()]
		assert len(sec_warnings) > 0

	def test_qdrant_https_no_warn(self):
		"""Lines 17: QDRANT_SCHEME=https → no SEC-F04 warning."""
		with warnings.catch_warnings(record=True) as w:
			warnings.simplefilter("always")
			_reimport_config({"QDRANT_SCHEME": "https", "QDRANT_HOST": "remote.example.com", "MILVUS_ENABLED": "False"})
		sec_warnings = [x for x in w if "SEC-F04" in str(x.message)]
		assert len(sec_warnings) == 0

	def test_milvus_unencrypted_non_local_warns(self):
		"""Lines 42-44: MILVUS_ENABLED=True + MILVUS_SECURE=False + non-local → SEC-F03 forces True."""
		with warnings.catch_warnings(record=True) as w:
			warnings.simplefilter("always")
			mod = _reimport_config(
				{
					"QDRANT_SCHEME": "http",
					"QDRANT_HOST": "localhost",
					"MILVUS_ENABLED": "True",
					"MILVUS_SECURE": "False",
					"MILVUS_HOST": "milvus.remote.com",
				}
			)
		assert mod.MILVUS_SECURE is True


class TestConfigValidation:
	def test_invalid_decay_strategy_raises(self):
		"""Line 66: invalid DECAY_STRATEGY → ValueError."""
		with pytest.raises(ValueError, match="DECAY_STRATEGY"):
			_reimport_config({"DECAY_STRATEGY": "quantum", "MILVUS_ENABLED": "False"})

	def test_erosion_rate_out_of_bounds_raises(self):
		"""Line 85: EROSION_RATE > 1.0 → ValueError."""
		with pytest.raises(ValueError, match="EROSION_RATE"):
			_reimport_config({"EROSION_RATE": "1.5", "MILVUS_ENABLED": "False"})

	def test_propagation_factor_out_of_bounds_raises(self):
		"""Line 87: PROPAGATION_FACTOR > 1.0 → ValueError."""
		with pytest.raises(ValueError, match="PROPAGATION_FACTOR"):
			_reimport_config({"PROPAGATION_FACTOR": "2.0", "MILVUS_ENABLED": "False"})

	def test_metabolism_state_file_env_override(self):
		"""Line 223: METABOLISM_STATE_FILE env set → overrides default path."""
		mod = _reimport_config({"METABOLISM_STATE_FILE": "/custom/path/state.json", "MILVUS_ENABLED": "False"})
		assert mod.METABOLISM_STATE_FILE == "/custom/path/state.json"
