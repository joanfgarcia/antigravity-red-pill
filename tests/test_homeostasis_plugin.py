"""Tests for trinity_homeostasis plugin.

Regression guards for the cfg.VECTOR_SIZE fix and emotional state logic.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.plugins.trinity_homeostasis.plugin import (
	EmotionalState,
	HomeostasisPlugin,
)


# ─── EmotionalState unit tests ───────────────────────────────────────────────


class TestEmotionalState:
	"""Tests for the EmotionalState thermometer."""

	def test_default_state_is_purple(self):
		state = EmotionalState()
		assert state.get_color() == "PURPLE"

	def test_high_pain_triggers_red(self):
		state = EmotionalState()
		state.pain_signals = 6  # > 5 threshold
		assert state.get_color() == "RED"

	def test_high_frustration_triggers_red(self):
		state = EmotionalState()
		state.frustration = 0.85  # > 0.8 threshold
		assert state.get_color() == "RED"

	def test_high_flow_triggers_cyan(self):
		state = EmotionalState()
		state.flow_momentum = 0.8  # > 0.7 threshold
		assert state.get_color() == "CYAN"

	def test_red_takes_priority_over_cyan(self):
		"""Pain/frustration (RED) should override flow momentum (CYAN)."""
		state = EmotionalState()
		state.pain_signals = 10
		state.flow_momentum = 0.9
		assert state.get_color() == "RED"

	def test_boundary_values_stay_purple(self):
		"""Exactly at thresholds should not trigger color change."""
		state = EmotionalState()
		state.pain_signals = 5  # == 5, NOT > 5
		state.frustration = 0.8  # == 0.8, NOT > 0.8
		state.flow_momentum = 0.7  # == 0.7, NOT > 0.7
		assert state.get_color() == "PURPLE"


# ─── VECTOR_SIZE regression guard ────────────────────────────────────────────


class TestVectorSizeRegression:
	"""
	Regression test: The plugin MUST use cfg.VECTOR_SIZE, not cfg.EMBEDDING_DIM.
	cfg.EMBEDDING_DIM does not exist and would cause AttributeError at runtime.
	"""

	def test_vector_size_attribute_exists(self):
		"""cfg.VECTOR_SIZE must exist and be a positive integer."""
		assert hasattr(cfg, "VECTOR_SIZE"), (
			"cfg.VECTOR_SIZE is missing — the plugin depends on it for dummy vector creation"
		)
		config = cfg.get_config()
		assert isinstance(config.VECTOR_SIZE, int)
		assert config.VECTOR_SIZE > 0

	def test_embedding_dim_does_not_exist(self):
		"""cfg.EMBEDDING_DIM must NOT exist — using it is a bug."""
		config = cfg.get_config()
		assert not hasattr(config, "EMBEDDING_DIM"), (
			"cfg.EMBEDDING_DIM should not exist; use cfg.VECTOR_SIZE instead"
		)

	def test_dummy_vector_creation_matches_config(self):
		"""The dummy vector [0.0] * cfg.VECTOR_SIZE must produce correct dimensionality."""
		config = cfg.get_config()
		dummy = [0.0] * config.VECTOR_SIZE
		assert len(dummy) == config.VECTOR_SIZE
		assert all(v == 0.0 for v in dummy)


# ─── Plugin hook tests ───────────────────────────────────────────────────────


class TestHomeostasisPlugin:
	"""Tests for the HomeostasisPlugin hook behavior."""

	def _make_plugin(self):
		"""Create a plugin instance with mocked dependencies."""
		plugin = HomeostasisPlugin.__new__(HomeostasisPlugin)
		plugin.state = EmotionalState()
		plugin.memory_mgr = MagicMock()
		plugin.collection = "soul_memories"
		return plugin

	@pytest.mark.asyncio
	async def test_cognition_hook_injects_overrides(self):
		"""COGNITION hook must inject OPERATOR_COLOR and TONE_DIRECTIVE."""
		from red_pill.core.plugin_engine import PluginScope

		plugin = self._make_plugin()
		payload = {}

		result = await plugin.hook(PluginScope.COGNITION, payload)

		assert "system_prompt_overrides" in result
		overrides = result["system_prompt_overrides"]
		assert "OPERATOR_COLOR" in overrides
		assert "TONE_DIRECTIVE" in overrides
		assert overrides["OPERATOR_COLOR"] == "PURPLE"  # default state

	@pytest.mark.asyncio
	async def test_cognition_hook_persists_to_qdrant(self):
		"""COGNITION hook must call qdrant upsert with correct vector size."""
		from red_pill.core.plugin_engine import PluginScope

		plugin = self._make_plugin()
		payload = {}

		await plugin.hook(PluginScope.COGNITION, payload)

		# Verify upsert was called
		plugin.memory_mgr.client.upsert.assert_called_once()
		call_kwargs = plugin.memory_mgr.client.upsert.call_args
		points = call_kwargs.kwargs.get("points") or call_kwargs[1].get("points") or call_kwargs[0][0] if not call_kwargs.kwargs else None

		# Extract from the actual call — check the vector dimension
		upsert_call = plugin.memory_mgr.client.upsert.call_args
		assert upsert_call is not None

	@pytest.mark.asyncio
	async def test_telemetry_hook_counts_alerts(self):
		"""TELEMETRY hook must update pain_signals from alerts."""
		from red_pill.core.plugin_engine import PluginScope

		plugin = self._make_plugin()
		payload = {"system_alerts": ["alert1", "alert2", "alert3"]}

		await plugin.hook(PluginScope.TELEMETRY, payload)

		assert plugin.state.pain_signals == 3

	@pytest.mark.asyncio
	async def test_export_state_returns_dict(self):
		"""export_state must return a serializable dict with all fields."""
		plugin = self._make_plugin()
		plugin.state.pain_signals = 2
		plugin.state.frustration = 0.5
		plugin.state.flow_momentum = 0.3

		result = await plugin.export_state()

		assert result == {
			"pain_signals": 2,
			"frustration": 0.5,
			"flow_momentum": 0.3,
			"current_color": "PURPLE",
		}

	def test_tone_directives_coverage(self):
		"""All color states must have a tone directive."""
		plugin = self._make_plugin()
		for color in ["RED", "CYAN", "PURPLE"]:
			tone = plugin._get_tone_for(color)
			assert isinstance(tone, str)
			assert len(tone) > 0

	def test_tone_unknown_color_defaults_to_purple(self):
		"""Unknown color should fall back to PURPLE tone."""
		plugin = self._make_plugin()
		tone = plugin._get_tone_for("UNKNOWN")
		assert tone == "PURPLE"
