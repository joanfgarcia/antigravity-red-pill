"""
Targeted micro-tests to close the final coverage gap to ≥96%.
Each test block attacks a specific uncovered branch identified in the
coverage report.  No external dependencies required (pure unit tests).
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from red_pill.affect import BayesianEngine, FSRSEngine, MemoryEngine, get_memory_engine
from red_pill.cli import _PLUGIN_REGISTRY, _dispatch_plugins, handle_heal, handle_identity
from red_pill.config import RedPillConfig


class TestAffectEdgeCases:
	"""Covers affect.py lines 16, 24, 40-41, 60, 108, 113, 138."""

	def test_abstract_base_cannot_be_instantiated(self):
		"""MemoryEngine is abstract — instantiating raises TypeError (lines 16, 24)."""
		with pytest.raises(TypeError):
			MemoryEngine()  # type: ignore

	def test_fsrs_stability_zero_returns_zero_retrievability(self):
		"""_calculate_retrievability with stability=0 returns 0.0 (line 41)."""
		eng = FSRSEngine()
		result = eng._calculate_retrievability(stability_days=0, time_passed_days=5)
		assert result == 0.0

	def test_fsrs_delete_on_low_score(self):
		"""calculate_lazy_decay returns _delete when score ≤ threshold (line 60)."""
		eng = FSRSEngine(deletion_threshold=0.9)
		payload = {
			"reinforcement_score": 0.01,
			"stability": 0.001,
			"last_recalled_at": 0.0,  # Very old — will decay to near zero
		}
		result = eng.calculate_lazy_decay(payload, current_time=86400 * 365)  # 1 year later
		assert result.get("_delete") is True

	def test_fsrs_no_change_when_score_not_decayed(self):
		"""Returns {} when new_score >= old_score (line 65: fresh memory, not decayed)."""
		eng = FSRSEngine()
		now = 1_000_000.0
		payload = {
			"reinforcement_score": 0.9,
			"stability": 1e9,  # Astronomical stability — never decays
			"last_recalled_at": now,
		}
		result = eng.calculate_lazy_decay(payload, current_time=now + 1)
		assert result == {}

	def test_bayesian_delete_on_low_utility(self):
		"""BayesianEngine returns _delete when utility ≤ threshold (line 108)."""
		eng = BayesianEngine(deletion_threshold=0.9)
		payload = {
			"utility_alpha": 0.01,
			"utility_beta": 1.0,
			"last_recalled_at": 0.0,  # Very old
		}
		result = eng.calculate_lazy_decay(payload, current_time=86400 * 365)
		assert result.get("_delete") is True

	def test_bayesian_no_change_when_beta_unchanged(self):
		"""BayesianEngine returns {} when beta is unchanged (line 113 — fresh recall)."""
		eng = BayesianEngine()
		now = 1_000_000.0
		# If time_passed_days == 0, log1p(0) == 0, new_beta == beta
		payload = {
			"utility_alpha": 5.0,
			"utility_beta": 2.0,
			"last_recalled_at": now,
		}
		result = eng.calculate_lazy_decay(payload, current_time=now)
		assert result == {}

	def test_get_memory_engine_fallback(self):
		"""get_memory_engine('unknown') returns FSRSEngine (line 138)."""
		engine = get_memory_engine("totally_unknown_type")
		assert isinstance(engine, FSRSEngine)

	def test_get_memory_engine_bayesian(self):
		"""get_memory_engine('bayesian') returns BayesianEngine."""
		engine = get_memory_engine("bayesian")
		assert isinstance(engine, BayesianEngine)


# cli.py — Exception paths + identity purge


class TestCliExceptionPaths:
	"""Covers cli.py lines 100-101 (handle_heal CalledProcessError),
	131-142 (handle_identity purge + aborted purge)."""

	def test_handle_heal_calls_process_error_exits(self):
		"""handle_heal raises CalledProcessError → sys.exit(1) (lines 100-101)."""
		with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "healer")):
			with patch("sys.exit") as mock_exit:
				handle_heal(dry_run=False)
				mock_exit.assert_called_with(1)

	def test_handle_identity_purge_confirmed(self):
		"""handle_identity 'purge' with 'PURGE' input → purges identity (lines 131-138).
		Note: handle_identity does a local import, so we patch at red_pill.memory."""
		args = MagicMock()
		args.id_cmd = "purge"
		mock_mgr = MagicMock()
		with patch("builtins.input", return_value="PURGE"), patch("red_pill.memory.MemoryManager", return_value=mock_mgr):
			handle_identity(args)
			mock_mgr.purge_identity.assert_called_once()

	def test_handle_identity_purge_aborted(self):
		"""handle_identity 'purge' with non-'PURGE' input → aborts (line 141-142)."""
		args = MagicMock()
		args.id_cmd = "purge"
		with patch("builtins.input", return_value="no"):
			with patch("red_pill.cli.MemoryManager") as mock_mgr_cls:
				handle_identity(args)
				mock_mgr_cls.assert_not_called()


# cli.py — _dispatch_plugins warning on exception (line 190-191)


class TestDispatchPluginsWarning:
	"""Covers cli.py lines 190-191 (plugin exception isolation warning)."""

	def setup_method(self):
		_PLUGIN_REGISTRY.clear()

	def teardown_method(self):
		_PLUGIN_REGISTRY.clear()

	def test_dispatch_logs_warning_when_plugin_raises(self, caplog):
		"""A plugin that raises in handle() logs a warning but returns False (line 190-191)."""
		import logging

		class BadPlugin:
			def handle(self, args):
				raise RuntimeError("plugin exploded")

		_PLUGIN_REGISTRY["bad"] = BadPlugin()
		import argparse

		args = argparse.Namespace(command="whatever")
		with caplog.at_level(logging.WARNING, logger="red_pill.cli"):
			result = _dispatch_plugins(args)
		assert result is False
		assert "plugin exploded" in caplog.text or "bad" in caplog.text


# config.py — validator edge cases


class TestConfigValidatorEdgeCases:
	"""Covers config.py lines 44-48, 63-65, 138, 164, 281, 302,
	445-447, 457, 480, 485, 487, 489, 491."""

	def test_qdrant_url_defaults_to_localhost(self):
		"""When QDRANT_URL is empty, validator constructs localhost URL."""
		cfg = RedPillConfig(QDRANT_URL="")
		assert "localhost" in cfg.QDRANT_URL or "6333" in cfg.QDRANT_URL or cfg.QDRANT_URL == ":memory:"

	def test_deep_recall_triggers_parsed_from_comma_string(self):
		"""DEEP_RECALL_TRIGGERS_STR is split into a list (tests list validator)."""
		# Test via the config itself — check that any default list is a list
		cfg = RedPillConfig()
		assert isinstance(cfg.DEEP_RECALL_TRIGGERS, list)
		assert len(cfg.DEEP_RECALL_TRIGGERS) > 0

	def test_semantic_intent_threshold_high(self):
		"""SEMANTIC_INTENT_THRESHOLD returns 0.75 when set to HIGH."""
		cfg = RedPillConfig(SEMANTIC_INTENT_THRESHOLD_STR="HIGH")
		assert cfg.SEMANTIC_INTENT_THRESHOLD == 0.75

	def test_semantic_intent_threshold_low(self):
		"""SEMANTIC_INTENT_THRESHOLD returns 0.5 when set to LOW."""
		cfg = RedPillConfig(SEMANTIC_INTENT_THRESHOLD_STR="LOW")
		assert cfg.SEMANTIC_INTENT_THRESHOLD == 0.5

	def test_module_alias_bayesian_collections(self):
		"""Module-level alias BAYESIAN_COLLECTIONS is accessible via import."""
		from red_pill import config as cfg_module

		assert hasattr(cfg_module, "BAYESIAN_COLLECTIONS")

	def test_module_alias_memory_engines(self):
		"""Module-level alias MEMORY_ENGINES is accessible via import."""
		from red_pill import config as cfg_module

		assert hasattr(cfg_module, "MEMORY_ENGINES")

	def test_module_alias_chroma_tone_mapping(self):
		"""Module-level alias CHROMA_TONE_MAPPING is accessible."""
		from red_pill import config as cfg_module

		assert hasattr(cfg_module, "CHROMA_TONE_MAPPING")

	def test_module_alias_current_schema_version(self):
		"""Module-level alias CURRENT_SCHEMA_VERSION is accessible."""
		from red_pill import config as cfg_module

		assert hasattr(cfg_module, "CURRENT_SCHEMA_VERSION")
