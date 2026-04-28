import importlib
import time
from unittest.mock import MagicMock, patch

import pytest

from red_pill import config

plugin_module = importlib.import_module("red_pill.interceptors.11_pre_heating")
EmotionalPreHeatingPlugin = plugin_module.EmotionalPreHeatingPlugin
from red_pill.utils.pre_heating_scorer import composite_score, extract_contextual_metadata  # noqa: E402


@pytest.fixture(autouse=True)
def reset_plugin_state():
	EmotionalPreHeatingPlugin._has_fired = False
	yield
	EmotionalPreHeatingPlugin._has_fired = False


def mock_qdrant_point(color, intensity, created_at, content="dummy", category="social"):
	point = MagicMock()
	point.payload = {
		"color": color,
		"intensity": intensity,
		"created_at": created_at,
		"content": content,
		"category": category,
		"emotion": "neutral",
		"linguistic_markers": ["marker1"],
	}
	return point


@pytest.mark.asyncio
async def test_fires_once():
	plugin = EmotionalPreHeatingPlugin()

	with patch.object(plugin_module, "MemoryManager") as mock_mgr:
		# First call should output something if context exists
		mock_client = MagicMock()
		mock_client.collection_exists.return_value = False
		mock_mgr.return_value.client = mock_client

		await plugin.execute("hello")
		res2 = await plugin.execute("world")

		assert EmotionalPreHeatingPlugin._has_fired is True
		assert res2 == ""


@pytest.mark.asyncio
async def test_graceful_degradation():
	plugin = EmotionalPreHeatingPlugin()

	with patch.object(plugin_module, "MemoryManager") as mock_mgr:
		mock_client = MagicMock()
		mock_client.collection_exists.return_value = True

		mock_client.scroll.return_value = ([], None)
		mock_mgr.return_value.client = mock_client

		res = await plugin.execute("hello")
		assert "EMOTIONAL PRE-HEATING" not in res
		assert res == ""
		assert EmotionalPreHeatingPlugin._has_fired is True


@pytest.mark.asyncio
async def test_composite_scoring_logic():
	now = time.time()
	# High intensity, recent, bad color
	score1 = composite_score(10.0, "gray", now - 3600)  # 10 * 1.0 * 0.3 = 3.0
	# Medium intensity, recent, good color
	score2 = composite_score(8.0, "purple", now - 3600)  # 8 * 1.0 * 1.5 = 12.0
	# High intensity, old, good color
	score3 = composite_score(10.0, "purple", now - 400000)  # 10 * 0.2 * 1.5 = 3.0

	assert score2 > score1
	assert score2 > score3


@pytest.mark.asyncio
async def test_contextual_mode_extraction():
	payload = {
		"emotion": "sadness",
		"color": "purple",
		"linguistic_markers": ["loneliness", "fear", "anxiety", "ok", "hi"],
		"content": "I feel lost.",
	}

	meta = extract_contextual_metadata(payload)
	assert meta["tone"] == "quiet, reflective"
	assert meta["operator_state"] == "deep focus, philosophical"
	assert "loneliness" in meta["themes"]
	assert "hi" not in meta["themes"]  # len <= 3 filtered out


@pytest.mark.asyncio
async def test_raw_mode_truncation(monkeypatch):
	monkeypatch.setattr(config, "PRE_HEATING_INJECTION_MODE", "raw")
	monkeypatch.setattr(config, "PRE_HEATING_MAX_CHARS_PER_FRAGMENT", 10)

	plugin = EmotionalPreHeatingPlugin()
	with patch.object(plugin_module, "MemoryManager") as mock_mgr:
		mock_client = MagicMock()
		mock_client.collection_exists.return_value = True

		now = time.time()
		point = mock_qdrant_point("purple", 10.0, now, content="This is a very long string that should be truncated")
		mock_client.scroll.return_value = ([point], None)
		mock_mgr.return_value.client = mock_client

		res = await plugin.execute("hello")
		assert "This is a ..." in res
		assert "Themes" not in res


@pytest.mark.asyncio
async def test_disabled_by_config(monkeypatch):
	monkeypatch.setattr(config, "PRE_HEATING_ENABLED", False)
	plugin = EmotionalPreHeatingPlugin()
	assert plugin.is_enabled is False
