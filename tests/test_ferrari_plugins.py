"""
Tests for Ferrari Interceptor Plugins 07–10.
All Qdrant/MemoryManager calls are mocked — no real I/O.

NOTE: Plugin modules start with digits (07_, 08_, ...) so they must be imported
via importlib.import_module rather than standard Python import syntax.
MemoryManager is imported lazily inside execute() via `from red_pill.memory import
MemoryManager`, so we patch at the source: `red_pill.memory.MemoryManager`.
"""

import asyncio
import importlib
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_point(color: str = "gray", text: str = "sample memory", immune: bool = False):
	import time

	p = MagicMock()
	p.payload = {"color": color, "text": text, "immune": immune, "created_at": time.time()}
	return p


def _mock_scroll(colors: list[str]):
	points = [_make_point(c) for c in colors]
	return points, None


def _mem_mock(scroll_colors: list[str] | None = None, search_results: list | None = None):
	"""Build a MemoryManager mock. scroll_colors overrides client.scroll(), search_results overrides search_memory()."""
	m = MagicMock()
	if scroll_colors is not None:
		m.client.scroll.return_value = _mock_scroll(scroll_colors)
	if search_results is not None:
		m.search_and_reinforce.return_value = search_results
	return m


# ---------------------------------------------------------------------------
# 07 — Mood Analytics
# ---------------------------------------------------------------------------


class TestMoodAnalyticsPlugin:
	def _get_plugin(self):
		mod = importlib.import_module("red_pill.interceptors.07_mood_analytics")
		return mod.MoodAnalyticsPlugin()

	def test_name_and_timeout(self):
		p = self._get_plugin()
		assert "Mood Analytics" in p.name
		assert p.timeout <= 2.0

	def test_enabled_by_default(self):
		p = self._get_plugin()
		assert p.is_enabled is True

	def test_returns_block_with_data(self):
		p = self._get_plugin()
		colors = ["purple"] * 5 + ["cyan"] * 3 + ["gray"] * 4
		mock_mem = _mem_mock(scroll_colors=colors)
		with patch("red_pill.memory.MemoryManager", return_value=mock_mem):
			result = asyncio.run(p.execute("test"))
		assert "MOOD ANALYTICS" in result
		assert "PURPLE" in result or "CYAN" in result

	def test_returns_empty_on_no_points(self):
		p = self._get_plugin()
		mock_mem = _mem_mock(scroll_colors=[])
		with patch("red_pill.memory.MemoryManager", return_value=mock_mem):
			result = asyncio.run(p.execute("test"))
		assert result == ""

	def test_trend_labels(self):
		mod = importlib.import_module("red_pill.interceptors.07_mood_analytics")
		assert "deteriorat" in mod._trend_label(0.0, 3.0).lower()
		assert "improving" in mod._trend_label(4.0, 1.0).lower()
		assert "stable" in mod._trend_label(2.0, 2.0).lower()


# ---------------------------------------------------------------------------
# 08 — Emotive Recall
# ---------------------------------------------------------------------------


class TestEmotiveRecallPlugin:
	def _get_plugin(self):
		mod = importlib.import_module("red_pill.interceptors.08_emotive_recall")
		return mod.EmotiveRecallPlugin()

	def test_name_and_timeout(self):
		p = self._get_plugin()
		assert "Emotive Recall" in p.name
		assert p.timeout <= 3.0

	def test_skips_gray_state(self):
		p = self._get_plugin()
		mod = importlib.import_module("red_pill.interceptors.08_emotive_recall")
		with patch.object(mod, "get_current_sync_state", return_value={"mood": "gray"}):
			result = asyncio.run(p.execute("test"))
		assert result == ""

	def test_returns_echo_for_color_state(self):
		p = self._get_plugin()
		mod = importlib.import_module("red_pill.interceptors.08_emotive_recall")
		r = MagicMock()
		r.payload = {"content": "Designing Ariadne's Thread", "color": "cyan"}
		mock_mem = _mem_mock(search_results=[r])
		with (
			patch.object(mod, "get_current_sync_state", return_value={"mood": "cyan"}),
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
		):
			result = asyncio.run(p.execute("test"))
		assert "EMOTIVE RECALL" in result
		assert "CYAN" in result
		assert "Ariadne" in result  # regression: engram content must reach the prompt

	def test_returns_empty_on_no_results(self):
		p = self._get_plugin()
		mod = importlib.import_module("red_pill.interceptors.08_emotive_recall")
		mock_mem = _mem_mock(search_results=[])
		with (
			patch.object(mod, "get_current_sync_state", return_value={"mood": "red"}),
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
		):
			result = asyncio.run(p.execute("test"))
		assert result == ""


# ---------------------------------------------------------------------------
# 09 — Proactive Signal
# ---------------------------------------------------------------------------


class TestProactiveSignalPlugin:
	def setup_method(self):
		mod = importlib.import_module("red_pill.interceptors.09_proactive_signal")
		mod._pain_signal_emitted = False  # type: ignore

	def _get_plugin(self):
		mod = importlib.import_module("red_pill.interceptors.09_proactive_signal")
		return mod.ProactiveSignalPlugin()

	def _cfg(self, threshold: int = 5):
		return MagicMock(PROACTIVE_SIGNAL_ENABLED=True, PROACTIVE_SIGNAL_RED_THRESHOLD=threshold)

	def test_name_and_timeout(self):
		p = self._get_plugin()
		assert "Proactive Signal" in p.name
		assert p.timeout <= 3.0

	def test_returns_empty_when_healthy(self):
		p = self._get_plugin()
		mock_mem = _mem_mock(scroll_colors=["cyan"] * 6)
		with (
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
			patch("red_pill.config.get_config", return_value=self._cfg()),
		):
			result = asyncio.run(p.execute("test"))
		assert result == ""

	def test_alerts_on_sustained_red(self):
		p = self._get_plugin()
		mock_mem = _mem_mock(scroll_colors=["red"] * 7 + ["cyan"] * 3)
		with (
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
			patch("red_pill.config.get_config", return_value=self._cfg()),
		):
			result = asyncio.run(p.execute("test"))
		assert "PROACTIVE SIGNAL" in result
		assert "RED" in result

	def test_alerts_on_high_volatility(self):
		p = self._get_plugin()
		# 4 color changes in 5 → high volatility
		mock_mem = _mem_mock(scroll_colors=["cyan", "red", "yellow", "blue", "gray", "gray", "gray"])
		with (
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
			patch("red_pill.config.get_config", return_value=self._cfg()),
		):
			result = asyncio.run(p.execute("test"))
		assert "volatil" in result.lower() or "VOLATILE" in result.upper()


# ---------------------------------------------------------------------------
# 10 — Predictive Preload
# ---------------------------------------------------------------------------


class TestPredictivePreloadPlugin:
	def _get_plugin(self):
		mod = importlib.import_module("red_pill.interceptors.10_predictive_preload")
		return mod.PredictivePreloadPlugin()

	def test_name_and_timeout(self):
		p = self._get_plugin()
		assert "Predictive Preload" in p.name
		assert p.timeout <= 3.0

	@pytest.mark.parametrize("color", ["gray", "orange", "yellow"])
	def test_skips_unmapped_colors(self, color: str):
		p = self._get_plugin()
		mod = importlib.import_module("red_pill.interceptors.10_predictive_preload")
		with patch.object(mod, "get_current_sync_state", return_value={"mood": color}):
			result = asyncio.run(p.execute("test"))
		assert result == ""

	def test_preloads_work_memories_for_cyan(self):
		p = self._get_plugin()
		mod = importlib.import_module("red_pill.interceptors.10_predictive_preload")
		r = MagicMock()
		r.payload = {"content": "Designing Ariadne's Thread axon system"}
		mock_mem = _mem_mock(search_results=[r])
		with (
			patch.object(mod, "get_current_sync_state", return_value={"mood": "cyan"}),
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
		):
			result = asyncio.run(p.execute("test"))
		assert "PREDICTIVE PRELOAD" in result
		assert "work_memories" in result
		assert "Ariadne" in result  # regression: engram content must reach the prompt

	def test_preloads_social_memories_for_blue(self):
		p = self._get_plugin()
		mod = importlib.import_module("red_pill.interceptors.10_predictive_preload")
		r = MagicMock()
		r.payload = {"content": "Operator shared feelings about isolation"}
		mock_mem = _mem_mock(search_results=[r])
		with (
			patch.object(mod, "get_current_sync_state", return_value={"mood": "blue"}),
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
		):
			result = asyncio.run(p.execute("test"))
		assert "PREDICTIVE PRELOAD" in result
		assert "social_memories" in result
		assert "isolation" in result  # regression: engram content must reach the prompt

	def test_returns_empty_on_no_results(self):
		p = self._get_plugin()
		mod = importlib.import_module("red_pill.interceptors.10_predictive_preload")
		mock_mem = _mem_mock(search_results=[])
		with (
			patch.object(mod, "get_current_sync_state", return_value={"mood": "purple"}),
			patch("red_pill.memory.MemoryManager", return_value=mock_mem),
		):
			result = asyncio.run(p.execute("test"))
		assert result == ""
