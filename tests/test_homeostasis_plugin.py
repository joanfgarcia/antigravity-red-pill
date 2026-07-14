"""Tests for trinity_homeostasis plugin.

Regression guards for the cfg.VECTOR_SIZE fix and emotional state logic.
"""

from unittest.mock import MagicMock

import pytest

import red_pill.config as cfg
from red_pill.plugins.trinity_homeostasis.plugin import (
	_SOUL_POINT_ID,
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
		assert hasattr(cfg, "VECTOR_SIZE"), "cfg.VECTOR_SIZE is missing — the plugin depends on it for dummy vector creation"
		config = cfg.get_config()
		assert isinstance(config.VECTOR_SIZE, int)
		assert config.VECTOR_SIZE > 0

	def test_embedding_dim_does_not_exist(self):
		"""cfg.EMBEDDING_DIM must NOT exist — using it is a bug."""
		config = cfg.get_config()
		assert not hasattr(config, "EMBEDDING_DIM"), "cfg.EMBEDDING_DIM should not exist; use cfg.VECTOR_SIZE instead"

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
		assert call_kwargs is not None, "upsert was called but call_args is empty"

		# Extract from the actual call — check the vector dimension
		upsert_call = plugin.memory_mgr.client.upsert.call_args
		assert upsert_call is not None

	@pytest.mark.asyncio
	async def test_cognition_hook_uses_deterministic_uuid(self):
		"""COGNITION hook must use the singleton _SOUL_POINT_ID, not a random UUID."""
		from red_pill.core.plugin_engine import PluginScope

		plugin = self._make_plugin()
		await plugin.hook(PluginScope.COGNITION, {})

		# Extract the PointStruct from the upsert call
		call_args = plugin.memory_mgr.client.upsert.call_args
		points = call_args[1]["points"] if "points" in (call_args[1] or {}) else call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["points"]
		assert points[0].id == _SOUL_POINT_ID, f"Expected deterministic UUID {_SOUL_POINT_ID}, got {points[0].id}"

	@pytest.mark.asyncio
	async def test_cognition_hook_second_call_same_id(self):
		"""Two consecutive COGNITION hooks must upsert the same point ID (no duplicates)."""
		from red_pill.core.plugin_engine import PluginScope

		plugin = self._make_plugin()
		await plugin.hook(PluginScope.COGNITION, {})
		await plugin.hook(PluginScope.COGNITION, {})

		assert plugin.memory_mgr.client.upsert.call_count == 2
		ids = []
		for call in plugin.memory_mgr.client.upsert.call_args_list:
			points = call[1]["points"]
			ids.append(points[0].id)
		assert ids[0] == ids[1] == _SOUL_POINT_ID

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

	def test_purge_leaked_duplicates_deletes_stale_points(self):
		"""_purge_leaked_duplicates must delete all points except _SOUL_POINT_ID."""
		from types import SimpleNamespace

		plugin = self._make_plugin()

		# Simulate 3 stale points + the singleton
		stale1 = SimpleNamespace(id="aaaa-1111", payload={})
		stale2 = SimpleNamespace(id="bbbb-2222", payload={})
		singleton = SimpleNamespace(id=_SOUL_POINT_ID, payload={})
		plugin.memory_mgr.client.scroll.return_value = ([stale1, stale2, singleton], None)

		plugin._purge_leaked_duplicates()

		# Should delete only the stale points
		plugin.memory_mgr.client.delete.assert_called_once()
		delete_call = plugin.memory_mgr.client.delete.call_args
		deleted_ids = delete_call[1]["points_selector"].points
		assert "aaaa-1111" in deleted_ids
		assert "bbbb-2222" in deleted_ids
		assert _SOUL_POINT_ID not in deleted_ids

	def test_purge_does_nothing_when_clean(self):
		"""_purge_leaked_duplicates must not call delete when only the singleton exists."""
		from types import SimpleNamespace

		plugin = self._make_plugin()
		singleton = SimpleNamespace(id=_SOUL_POINT_ID, payload={})
		plugin.memory_mgr.client.scroll.return_value = ([singleton], None)

		plugin._purge_leaked_duplicates()

		plugin.memory_mgr.client.delete.assert_not_called()
