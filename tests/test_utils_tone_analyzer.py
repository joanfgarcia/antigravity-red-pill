"""Tests for utils/tone_analyzer.py — targeting lines 88, 99-104."""

from unittest.mock import MagicMock, patch

import red_pill.config as cfg
from red_pill.utils.tone_analyzer import ToneAnalyzer, get_current_sync_state


class TestGetDominantMood:
	def _make_manager(self, points, fallback_exception=None):
		mgr = MagicMock()
		if fallback_exception:
			mgr.client.scroll.side_effect = [fallback_exception, (points, None)]
		else:
			mgr.client.scroll.return_value = (points, None)
		return mgr

	def test_returns_default_when_no_points(self):
		"""Line 65: empty scroll → returns DEFAULT_COLOR."""
		mgr = self._make_manager([])
		result = ToneAnalyzer.get_dominant_mood(manager=mgr)
		assert result == str(getattr(cfg, "HEDONIC_SET_POINT_COLOR", cfg.DEFAULT_COLOR))

	def test_returns_non_neutral_color_immediately(self):
		"""Line 74: first non-default color found → returned immediately."""
		import time
		p1 = MagicMock()
		p1.payload = {"color": "red", "immune": False, "created_at": time.time()}
		mgr = self._make_manager([p1])
		result = ToneAnalyzer.get_dominant_mood(manager=mgr)
		assert result == "red"

	def test_fallback_scroll_on_order_by_exception(self):
		"""Lines 55-62: order_by scroll fails → fallback to basic scroll."""
		import time
		p1 = MagicMock()
		p1.payload = {"color": "orange", "immune": False, "created_at": time.time()}
		mgr = self._make_manager([p1], fallback_exception=Exception("order_by not supported"))
		result = ToneAnalyzer.get_dominant_mood(manager=mgr)
		assert result == "orange"

	def test_all_default_color_returns_default(self):
		"""Lines 75-76: all points have default color → latest_color set, returned at end."""
		import time
		p1 = MagicMock()
		p1.payload = {"color": cfg.DEFAULT_COLOR, "immune": False, "created_at": time.time()}
		p2 = MagicMock()
		p2.payload = {"color": cfg.DEFAULT_COLOR, "immune": False, "created_at": time.time()}
		mgr = self._make_manager([p1, p2])
		result = ToneAnalyzer.get_dominant_mood(manager=mgr)
		assert result == str(getattr(cfg, "HEDONIC_SET_POINT_COLOR", cfg.DEFAULT_COLOR))

	def test_outer_exception_returns_default(self):
		"""Lines 79-81: outer exception → returns DEFAULT_COLOR."""
		mgr = MagicMock()
		mgr.client.scroll.side_effect = RuntimeError("Qdrant connection refused")
		result = ToneAnalyzer.get_dominant_mood(manager=mgr)
		assert result == str(getattr(cfg, "HEDONIC_SET_POINT_COLOR", cfg.DEFAULT_COLOR))

	def test_immune_points_skipped(self):
		"""Line 71: immune=True → skipped, returns default."""
		import time
		p1 = MagicMock()
		p1.payload = {"color": "red", "immune": True, "created_at": time.time()}
		mgr = self._make_manager([p1])
		result = ToneAnalyzer.get_dominant_mood(manager=mgr)
		assert result == str(getattr(cfg, "HEDONIC_SET_POINT_COLOR", cfg.DEFAULT_COLOR))


class TestGetToneDirective:
	def test_known_color_returns_directive(self):
		"""Line 88: known color → correct directive from CHROMA_TONE_MAPPING."""
		for color, directive in cfg.CHROMA_TONE_MAPPING.items():
			result = ToneAnalyzer.get_tone_directive(color)
			assert result == directive
			break

	def test_unknown_color_returns_default_directive(self):
		"""Line 88: unknown color → falls back to DEFAULT_COLOR directive."""
		result = ToneAnalyzer.get_tone_directive("ultraviolet_unknown")
		assert result == cfg.CHROMA_TONE_MAPPING[cfg.DEFAULT_COLOR]


class TestGetCurrentSyncState:
	def test_returns_default_when_dynamic_sync_disabled(self):
		"""Lines 99-100: DYNAMIC_EMOTION_SYNC=False → static default."""
		with patch.object(cfg, "DYNAMIC_EMOTION_SYNC", False):
			result = get_current_sync_state()
		assert result["mood"] == cfg.DEFAULT_COLOR
		assert result["directive"] == cfg.CHROMA_TONE_MAPPING[cfg.DEFAULT_COLOR]

	def test_returns_mood_and_directive_when_enabled(self):
		"""Lines 102-104: DYNAMIC_EMOTION_SYNC=True → mood + directive returned."""
		with patch.object(cfg, "DYNAMIC_EMOTION_SYNC", True):
			with patch.object(ToneAnalyzer, "get_dominant_mood", return_value="red"):
				with patch.object(ToneAnalyzer, "get_tone_directive", return_value="assertive"):
					result = get_current_sync_state()
		assert result["mood"] == "red"
		assert result["directive"] == "assertive"

	def test_passes_manager_through(self):
		"""Line 102: manager arg is forwarded to get_dominant_mood."""
		mock_mgr = MagicMock()
		with patch.object(cfg, "DYNAMIC_EMOTION_SYNC", True):
			with patch.object(ToneAnalyzer, "get_dominant_mood", return_value=cfg.DEFAULT_COLOR) as mock_mood:
				get_current_sync_state(manager=mock_mgr)
				mock_mood.assert_called_once_with(manager=mock_mgr)
