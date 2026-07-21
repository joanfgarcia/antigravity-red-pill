"""Tests for the Mood Orchestrator (interceptors/05_mood_orchestrator.py).

Module name starts with a digit → import via importlib. Subplugins are mocked, so
no Qdrant/Bünker I/O: we drive execute() to cover the raw_enabled gate, per-
subplugin error isolation, and the chroma-key emission.
"""

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import red_pill.config as cfg


@pytest.fixture
def orch_mod():
	return importlib.import_module("red_pill.interceptors.05_mood_orchestrator")


def _sp(name, output, *, raw_enabled=True, timeout=2.0, raises=None):
	sp = MagicMock()
	sp.name = name
	sp.raw_enabled = raw_enabled
	sp.timeout = timeout
	sp.execute = AsyncMock(side_effect=raises) if raises else AsyncMock(return_value=output)
	return sp


async def test_runs_enabled_subplugins_and_appends_chroma(orch_mod):
	sps = [_sp("A", "outA"), _sp("B", "outB")]
	with (
		patch.object(orch_mod, "_SUBPLUGINS", ["x", "y"]),
		patch.object(orch_mod, "_load_subplugin", side_effect=sps),
		patch("red_pill.utils.tone_analyzer.get_current_sync_state", return_value={"mood": "red"}),
	):
		out = await orch_mod.MoodOrchestratorPlugin().execute("hi")
	assert "outA" in out and "outB" in out
	assert "chroma: red" in out


async def test_skips_subplugin_with_raw_enabled_false(orch_mod):
	disabled = _sp("A", "outA", raw_enabled=False)
	enabled = _sp("B", "outB")
	with (
		patch.object(orch_mod, "_SUBPLUGINS", ["x", "y"]),
		patch.object(orch_mod, "_load_subplugin", side_effect=[disabled, enabled]),
		patch("red_pill.utils.tone_analyzer.get_current_sync_state", return_value={"mood": "gray"}),
	):
		out = await orch_mod.MoodOrchestratorPlugin().execute("hi")
	disabled.execute.assert_not_called()  # gated out by raw_enabled
	assert "outA" not in out
	assert "outB" in out


async def test_error_isolation_one_crash_does_not_stop_others(orch_mod):
	crashing = _sp("A", None, raises=RuntimeError("boom"))
	healthy = _sp("B", "outB")
	with (
		patch.object(orch_mod, "_SUBPLUGINS", ["x", "y"]),
		patch.object(orch_mod, "_load_subplugin", side_effect=[crashing, healthy]),
		patch.object(orch_mod, "_emit_pain_signal") as pain,
		patch("red_pill.utils.tone_analyzer.get_current_sync_state", return_value={"mood": "gray"}),
	):
		out = await orch_mod.MoodOrchestratorPlugin().execute("hi")
	assert "outB" in out  # healthy subplugin still ran
	pain.assert_called()  # crash emitted a pain signal, no exception propagated


async def test_returns_empty_when_no_subplugins_load(orch_mod):
	with (
		patch.object(orch_mod, "_SUBPLUGINS", ["x"]),
		patch.object(orch_mod, "_load_subplugin", return_value=None),
	):
		out = await orch_mod.MoodOrchestratorPlugin().execute("hi")
	assert out == ""


def test_is_enabled_tracks_orchestrator_flag(orch_mod):
	p = orch_mod.MoodOrchestratorPlugin()
	with patch.object(cfg.get_config(), "MOOD_ORCHESTRATOR_ENABLED", True):
		assert p.is_enabled is True
	with patch.object(cfg.get_config(), "MOOD_ORCHESTRATOR_ENABLED", False):
		assert p.is_enabled is False
