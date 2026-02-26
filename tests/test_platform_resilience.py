"""
TST-F02 / TST-F03: ToneAnalyzer Fallback & Platform Quirks
============================================================
TST-F02: Verifies ToneAnalyzer.get_dominant_mood() falls back gracefully
         when the ordered scroll fails (no order_by support on mock/old Qdrant).

TST-F03: Verifies that the Windows fcntl ImportError fallback in the
         metabolism state file handling is exercised cleanly — the system
         must not crash when fcntl is unavailable, it should degrade to
         no-op file locking.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg

# ─────────────────────────────────────────────────────────────────────────────
# TST-F02: ToneAnalyzer fallback scroll
# ─────────────────────────────────────────────────────────────────────────────


class TestToneAnalyzerFallback:
	"""TST-F02: get_dominant_mood() must degrade gracefully on scroll failure."""

	def _make_point(self, color: str, immune: bool = False) -> MagicMock:
		p = MagicMock()
		p.payload = {"color": color, "immune": immune}
		return p

	def test_fallback_scroll_returns_color_on_ordered_failure(self):
		"""
		When the ordered scroll raises an exception (e.g. old Qdrant without
		order_by support), get_dominant_mood() retries with a plain scroll
		and returns the dominant color.
		"""
		from red_pill.utils.tone_analyzer import ToneAnalyzer

		mock_manager = MagicMock()
		orange_point = self._make_point("orange")

		# First call (ordered) raises, second call (plain) succeeds
		mock_manager.client.scroll.side_effect = [
			Exception("order_by not supported"),
			([orange_point], None),
		]

		result = ToneAnalyzer.get_dominant_mood(manager=mock_manager)
		assert result == "orange"
		assert mock_manager.client.scroll.call_count == 2

	def test_fallback_scroll_returns_default_on_double_failure(self):
		"""If both scrolls fail, get_dominant_mood() returns DEFAULT_COLOR (graceful)."""
		from red_pill.utils.tone_analyzer import ToneAnalyzer

		mock_manager = MagicMock()
		mock_manager.client.scroll.side_effect = Exception("DB offline")

		result = ToneAnalyzer.get_dominant_mood(manager=mock_manager)
		assert result == cfg.DEFAULT_COLOR

	def test_no_immune_points_returns_default(self):
		"""If only immune points exist, returns DEFAULT_COLOR (they are filtered out)."""
		from red_pill.utils.tone_analyzer import ToneAnalyzer

		mock_manager = MagicMock()
		immune_point = self._make_point("cyan", immune=True)
		mock_manager.client.scroll.return_value = ([immune_point], None)

		result = ToneAnalyzer.get_dominant_mood(manager=mock_manager)
		assert result == cfg.DEFAULT_COLOR

	def test_empty_collection_returns_default(self):
		"""Empty scroll result returns DEFAULT_COLOR."""
		from red_pill.utils.tone_analyzer import ToneAnalyzer

		mock_manager = MagicMock()
		mock_manager.client.scroll.return_value = ([], None)

		result = ToneAnalyzer.get_dominant_mood(manager=mock_manager)
		assert result == cfg.DEFAULT_COLOR

	def test_non_default_color_returned_first(self):
		"""First non-default color in the result wins (High Reactivity Logic)."""
		from red_pill.utils.tone_analyzer import ToneAnalyzer

		mock_manager = MagicMock()
		gray_point = self._make_point(cfg.DEFAULT_COLOR)
		yellow_point = self._make_point("yellow")
		mock_manager.client.scroll.return_value = ([gray_point, yellow_point], None)

		result = ToneAnalyzer.get_dominant_mood(manager=mock_manager)
		assert result == "yellow"

	def test_existing_manager_is_reused(self):
		"""PERF-F02: Passing an existing manager avoids creating a new connection."""
		from red_pill.utils.tone_analyzer import ToneAnalyzer

		mock_manager = MagicMock()
		mock_manager.client.scroll.return_value = ([], None)

		# If manager is passed, MemoryManager() constructor must NOT be called.
		# Patch at the source module since the import is done lazily inside the method.
		with patch("red_pill.memory.MemoryManager") as mock_cls:
			ToneAnalyzer.get_dominant_mood(manager=mock_manager)
			mock_cls.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# TST-F03: Windows fcntl fallback
# ─────────────────────────────────────────────────────────────────────────────


class TestWindowsFcntlFallback:
	"""
	TST-F03: Verify the metabolism state file handling degrades gracefully
	when fcntl is unavailable (Windows). The system must not raise ImportError
	or crash — it should silently skip advisory locking.
	"""

	def test_metabolism_cycle_survives_missing_fcntl(self, tmp_path):
		"""
		When fcntl is not importable (Windows), _run_metabolism_cycle() must
		complete without raising. It should read/write the state file normally
		but skip the flock calls.
		"""
		# Remove fcntl from sys.modules to simulate Windows
		fcntl_backup = sys.modules.get("fcntl")
		sys.modules["fcntl"] = None  # type: ignore

		try:
			state_file = tmp_path / "metabolism_state.json"
			cfg.METABOLISM_STATE_FILE = str(state_file)
			cfg.METABOLISM_ENABLED = True
			cfg.METABOLISM_COOLDOWN = 0  # Force cycle

			with patch("red_pill.memory.QdrantClient"), patch("red_pill.memory.MemoryManager.apply_erosion"):
				from red_pill.memory import MemoryManager

				manager = MemoryManager(url="http://mock:6333")
				# Should not raise even without fcntl
				try:
					manager._run_metabolism_cycle()
				except ImportError as e:
					pytest.fail(f"ImportError from missing fcntl — platform isolation failed: {e}")

		finally:
			# Restore fcntl
			if fcntl_backup is not None:
				sys.modules["fcntl"] = fcntl_backup
			elif "fcntl" in sys.modules:
				del sys.modules["fcntl"]

	def test_write_and_read_state_without_fcntl(self, tmp_path):
		"""
		_write_metabolism_state() and _read_metabolism_state() must work
		even if fcntl.flock() is unavailable — they should degrade to a
		plain file write/read without raising.
		"""

		fcntl_backup = sys.modules.get("fcntl")
		sys.modules["fcntl"] = None  # type: ignore

		try:
			state_file = tmp_path / "metabolism_test.json"
			cfg.METABOLISM_STATE_FILE = str(state_file)

			with patch("red_pill.memory.QdrantClient"):
				from red_pill.memory import MemoryManager

				manager = MemoryManager(url="http://mock:6333")

				with open(state_file, "w+") as f:
					try:
						manager._write_metabolism_state(f, 1234567890.0, skip_next_erosion=False)
					except ImportError as e:
						pytest.fail(f"write_metabolism_state raised ImportError without fcntl: {e}")

				with open(state_file, "r+") as f:
					try:
						last_run, skip = manager._read_metabolism_state(f)
					except ImportError as e:
						pytest.fail(f"read_metabolism_state raised ImportError without fcntl: {e}")

				assert last_run == pytest.approx(1234567890.0, abs=0.001)
				assert skip is False

		finally:
			if fcntl_backup is not None:
				sys.modules["fcntl"] = fcntl_backup
			elif "fcntl" in sys.modules:
				del sys.modules["fcntl"]
