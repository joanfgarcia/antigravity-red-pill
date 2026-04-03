"""
Tests for red_pill.config — RedPillConfig (Pydantic BaseSettings, v6.2.0).
Tests the cascade loading, security validators, and field validation.
"""

import warnings
from typing import Any

import pytest
from pydantic import ValidationError

from red_pill.config import RedPillConfig, _load_affect_multipliers


def _make_config(**kwargs: Any) -> RedPillConfig:
	"""
	Build a RedPillConfig with custom field overrides for testing.
	Bypasses the singleton cache entirely.
	"""
	return RedPillConfig(**kwargs)


class TestConfigWarnings:
	def test_qdrant_http_non_local_warns(self):
		"""SEC-F04: QDRANT_SCHEME=http + non-local host → UserWarning emitted."""
		with warnings.catch_warnings(record=True) as w:
			warnings.simplefilter("always")
			_make_config(
				QDRANT_HOST="remote.example.com",
				QDRANT_SCHEME="http",
				MILVUS_ENABLED=False,
			)
		sec_warnings = [x for x in w if "SEC-F04" in str(x.message) or "cleartext" in str(x.message).lower()]
		assert len(sec_warnings) > 0

	def test_qdrant_https_no_warn(self):
		"""QDRANT_SCHEME=https → no SEC-F04 warning."""
		with warnings.catch_warnings(record=True) as w:
			warnings.simplefilter("always")
			_make_config(
				QDRANT_HOST="remote.example.com",
				QDRANT_SCHEME="https",
				MILVUS_ENABLED=False,
			)
		sec_warnings = [x for x in w if "SEC-F04" in str(x.message)]
		assert len(sec_warnings) == 0

	def test_milvus_unencrypted_non_local_warns(self):
		"""SEC-F03: MILVUS_ENABLED=True + MILVUS_SECURE=False + non-local → forced to True."""
		cfg = _make_config(
			QDRANT_HOST="localhost",
			QDRANT_SCHEME="http",
			MILVUS_ENABLED=True,
			MILVUS_SECURE=False,
			MILVUS_HOST="milvus.remote.com",
		)
		assert cfg.MILVUS_SECURE is True


class TestConfigValidation:
	def test_invalid_decay_strategy_raises(self):
		"""Invalid DECAY_STRATEGY → ValidationError."""
		with pytest.raises((ValueError, ValidationError)):
			_make_config(DECAY_STRATEGY="quantum")

	def test_erosion_rate_out_of_bounds_raises(self):
		"""EROSION_RATE > 1.0 → ValidationError."""
		with pytest.raises((ValueError, ValidationError)):
			_make_config(EROSION_RATE=1.5)

	def test_propagation_factor_out_of_bounds_raises(self):
		"""PROPAGATION_FACTOR > 1.0 → ValidationError."""
		with pytest.raises((ValueError, ValidationError)):
			_make_config(PROPAGATION_FACTOR=2.0)

	def test_metabolism_state_file_env_override(self):
		"""METABOLISM_STATE_FILE field → overrides default path."""
		cfg = _make_config(METABOLISM_STATE_FILE="/custom/path/state.json")
		assert cfg.METABOLISM_STATE_FILE == "/custom/path/state.json"


class TestConfigModuleAliases:
	def test_module_aliases_resolve(self):
		"""Module-level aliases (cfg.QDRANT_HOST etc.) resolve via __getattr__."""
		import red_pill.config as cfg

		assert isinstance(cfg.QDRANT_HOST, str)
		assert isinstance(cfg.QDRANT_URL, str)
		assert cfg.QDRANT_URL.startswith("http") or cfg.QDRANT_URL == ":memory:"
		assert isinstance(cfg.EROSION_RATE, float)
		assert isinstance(cfg.DEEP_RECALL_TRIGGERS, list)
		assert "despierta" in cfg.DEEP_RECALL_TRIGGERS
		assert isinstance(cfg.BAYESIAN_COLLECTIONS, list)
		assert isinstance(cfg.MEMORY_ENGINES, dict)

	def test_get_config_returns_model(self):
		"""get_config() returns a RedPillConfig instance."""
		from red_pill.config import get_config

		cfg = get_config()
		assert isinstance(cfg, RedPillConfig)

	def test_enterprise_overrides_pattern(self):
		"""Enterprise can inject read-only overrides via get_enterprise()."""
		from red_pill.config import get_config, set_enterprise_overrides

		set_enterprise_overrides({"CERBERUS_TOKEN": "test-token-xyz"})
		cfg_inst = get_config()
		assert cfg_inst.get_enterprise("CERBERUS_TOKEN") == "test-token-xyz"
		assert cfg_inst.get_enterprise("NONEXISTENT_KEY", "default_val") == "default_val"
		# Clean up
		set_enterprise_overrides({"CERBERUS_TOKEN": ""})


class TestAffectMultipliers:
	def test_pioneer_model_loads(self):
		"""Default PIONEER affect model loads correct multipliers."""
		multipliers = _load_affect_multipliers("PIONEER")
		assert "orange" in multipliers
		assert isinstance(multipliers["orange"], float)

	def test_unknown_model_falls_back(self):
		"""Unknown affect model → falls back to PIONEER defaults."""
		with warnings.catch_warnings(record=True):
			warnings.simplefilter("always")
			multipliers = _load_affect_multipliers("NONEXISTENT_MODEL_XYZ")
		assert "orange" in multipliers
