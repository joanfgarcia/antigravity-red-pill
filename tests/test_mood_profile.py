"""Tests for the Operator Mood Profile (USP)."""

import time
from unittest.mock import MagicMock, patch

from red_pill.utils.mood_profile import (
	CHROMA_KEYS,
	HORIZONS,
	ID_OPERATOR_MOOD,
	_empty_vector,
	_get_dominant_color,
	calculate_resonance_vector,
	get_dominant_operator_mood,
	get_operator_mood,
	update_usp,
)


class TestEmptyVector:
	def test_returns_all_chroma_keys(self):
		v = _empty_vector()
		assert set(v.keys()) == set(CHROMA_KEYS)

	def test_all_values_zero(self):
		v = _empty_vector()
		assert all(val == 0.0 for val in v.values())


class TestGetDominantColor:
	def test_empty_vector_returns_default(self):
		assert _get_dominant_color({}) == "gray"

	def test_all_zeros_returns_default(self):
		assert _get_dominant_color(_empty_vector()) == "gray"

	def test_single_non_gray_dominates(self):
		v = _empty_vector()
		v["orange"] = 0.8
		assert _get_dominant_color(v) == "orange"

	def test_gray_excluded_from_dominance(self):
		v = _empty_vector()
		v["gray"] = 0.9
		v["blue"] = 0.1
		assert _get_dominant_color(v) == "blue"

	def test_highest_wins(self):
		v = _empty_vector()
		v["purple"] = 0.3
		v["cyan"] = 0.7
		assert _get_dominant_color(v) == "cyan"


class TestCalculateResonanceVector:
	def _make_manager(self, points_by_collection=None):
		"""Creates a mock manager with configurable scroll results."""
		manager = MagicMock()
		points_by_collection = points_by_collection or {}

		def scroll_side_effect(collection_name, **kwargs):
			points = points_by_collection.get(collection_name, [])
			return points, None  # No pagination

		manager.client.scroll.side_effect = scroll_side_effect
		return manager

	def _make_point(self, color="gray", intensity=1.0, importance=1.0, created_at=None):
		"""Creates a mock Qdrant point."""
		p = MagicMock()
		p.payload = {
			"color": color,
			"intensity": intensity,
			"importance": importance,
			"created_at": created_at or time.time(),
			"immune": False,
		}
		return p

	def test_no_engrams_returns_zero_vector(self):
		manager = self._make_manager()
		result = calculate_resonance_vector(manager, 3 * 86400)
		assert all(v == 0.0 for v in result.values())

	def test_single_color_dominates(self):
		p = self._make_point(color="orange", intensity=5.0, importance=2.0)
		manager = self._make_manager({"work_memories": [p], "social_memories": []})
		result = calculate_resonance_vector(manager, 3 * 86400)
		assert result["orange"] == 1.0
		assert all(result[k] == 0.0 for k in CHROMA_KEYS if k != "orange")

	def test_two_colors_weighted(self):
		p1 = self._make_point(color="orange", intensity=2.0, importance=1.0)  # weight=2
		p2 = self._make_point(color="blue", intensity=3.0, importance=1.0)  # weight=3
		manager = self._make_manager({"work_memories": [p1, p2], "social_memories": []})
		result = calculate_resonance_vector(manager, 3 * 86400)
		assert abs(result["orange"] - 0.4) < 0.01  # 2/5
		assert abs(result["blue"] - 0.6) < 0.01  # 3/5

	def test_global_horizon_no_time_filter(self):
		manager = self._make_manager({"work_memories": [], "social_memories": []})
		calculate_resonance_vector(manager, 0)  # global
		# Verify no time filter was used (only immune filter)
		call_args = manager.client.scroll.call_args_list[0]
		scroll_filter = call_args[1]["scroll_filter"]
		assert len(scroll_filter.must) == 1  # Only immune filter

	def test_scroll_exception_returns_partial(self):
		manager = MagicMock()
		manager.client.scroll.side_effect = Exception("DB down")
		result = calculate_resonance_vector(manager, 3 * 86400)
		assert all(v == 0.0 for v in result.values())

	def test_unknown_color_ignored(self):
		p = self._make_point(color="invalid_color")
		manager = self._make_manager({"work_memories": [p], "social_memories": []})
		result = calculate_resonance_vector(manager, 3 * 86400)
		assert all(v == 0.0 for v in result.values())


class TestUpdateUSP:
	def test_creates_usp_engram(self):
		manager = MagicMock()
		manager.client.retrieve.return_value = []
		manager.client.scroll.return_value = ([], None)
		manager.add_memory.return_value = ID_OPERATOR_MOOD

		usp = update_usp(manager)

		assert usp["type"] == "operator_mood_profile"
		assert "last_3d" in usp
		assert "last_7d" in usp
		assert "last_30d" in usp
		assert "global" in usp
		assert usp["interaction_count"] == 1

		# Verify add_memory was called with the fixed ID
		manager.add_memory.assert_called_once()
		call_kwargs = manager.add_memory.call_args[1]
		assert call_kwargs["point_id"] == ID_OPERATOR_MOOD
		assert call_kwargs["force_immune"] is True

	def test_increments_interaction_count(self):
		manager = MagicMock()
		existing = MagicMock()
		existing.payload = {"interaction_count": 41}
		manager.client.retrieve.return_value = [existing]
		manager.client.scroll.return_value = ([], None)
		manager.add_memory.return_value = ID_OPERATOR_MOOD

		usp = update_usp(manager)
		assert usp["interaction_count"] == 42

	def test_persists_all_horizons(self):
		manager = MagicMock()
		manager.client.retrieve.return_value = []
		manager.client.scroll.return_value = ([], None)
		manager.add_memory.return_value = ID_OPERATOR_MOOD

		usp = update_usp(manager)
		for horizon in HORIZONS:
			assert horizon in usp
			assert set(usp[horizon].keys()) == set(CHROMA_KEYS)


class TestGetOperatorMood:
	def test_returns_stored_vector(self):
		manager = MagicMock()
		stored_vector = {"orange": 0.7, "blue": 0.3}
		point = MagicMock()
		point.payload = {"last_3d": stored_vector}
		manager.client.retrieve.return_value = [point]

		result = get_operator_mood(manager, "last_3d")
		assert result == stored_vector

	def test_returns_empty_on_missing(self):
		manager = MagicMock()
		manager.client.retrieve.return_value = []

		result = get_operator_mood(manager, "last_3d")
		assert all(v == 0.0 for v in result.values())

	def test_returns_empty_on_exception(self):
		manager = MagicMock()
		manager.client.retrieve.side_effect = Exception("DB down")

		result = get_operator_mood(manager)
		assert all(v == 0.0 for v in result.values())


class TestGetDominantOperatorMood:
	def test_from_preloaded_usp(self):
		manager = MagicMock()
		usp = {"last_3d": {"orange": 0.8, "blue": 0.2, "gray": 0.0}}
		result = get_dominant_operator_mood(manager, usp=usp)
		assert result == "orange"

	def test_from_database(self):
		manager = MagicMock()
		point = MagicMock()
		point.payload = {"last_3d": {"purple": 0.6, "cyan": 0.4}}
		manager.client.retrieve.return_value = [point]

		result = get_dominant_operator_mood(manager)
		assert result == "purple"

	def test_all_zero_returns_default(self):
		manager = MagicMock()
		result = get_dominant_operator_mood(manager, usp={"last_3d": _empty_vector()})
		assert result == "gray"


class TestNullPayloadPoint:
	"""Covers mood_profile.py line 89 — point with None payload."""

	def test_null_payload_skipped(self):
		p_null = MagicMock()
		p_null.payload = None
		p_valid = MagicMock()
		p_valid.payload = {"color": "orange", "intensity": 2.0, "importance": 1.0, "immune": False}

		manager = MagicMock()
		manager.client.scroll.return_value = ([p_null, p_valid], None)

		result = calculate_resonance_vector(manager, 3 * 86400)
		assert result["orange"] == 1.0  # Only the valid point counted


class TestUpdateUSPExceptions:
	"""Covers mood_profile.py lines 129-130 and 148-149."""

	def test_retrieve_exception_sets_count_1(self):
		"""Line 129-130: retrieve raises, interaction_count defaults to 1."""
		manager = MagicMock()
		manager.client.retrieve.side_effect = Exception("DB unreachable")
		manager.client.scroll.return_value = ([], None)
		manager.add_memory.return_value = ID_OPERATOR_MOOD

		usp = update_usp(manager)
		assert usp["interaction_count"] == 1

	def test_add_memory_exception_still_returns_usp(self):
		"""Line 148-149: add_memory fails, function still returns USP."""
		manager = MagicMock()
		manager.client.retrieve.return_value = []
		manager.client.scroll.return_value = ([], None)
		manager.add_memory.side_effect = Exception("Write failed")

		usp = update_usp(manager)
		assert usp["type"] == "operator_mood_profile"
		assert "last_3d" in usp


class TestMultiCollectionAggregation:
	"""Tests that both work_memories and social_memories are queried."""

	def test_both_collections_contribute(self):
		p_work = MagicMock()
		p_work.payload = {"color": "blue", "intensity": 3.0, "importance": 1.0, "immune": False}
		p_social = MagicMock()
		p_social.payload = {"color": "purple", "intensity": 2.0, "importance": 1.0, "immune": False}

		manager = MagicMock()

		def scroll_by_collection(collection_name, **kwargs):
			if collection_name == "work_memories":
				return [p_work], None
			return [p_social], None

		manager.client.scroll.side_effect = scroll_by_collection

		result = calculate_resonance_vector(manager, 3 * 86400)
		assert result["blue"] > 0
		assert result["purple"] > 0
		assert abs(result["blue"] + result["purple"] - 1.0) < 0.01


class TestMystiqueUSPIntegration:
	"""Covers mystique.py line 47 — manager-based USP path."""

	def test_suggest_skin_with_manager(self):
		from red_pill.utils.mystique import MystiqueEngine

		engine = MystiqueEngine()
		manager = MagicMock()

		# Mock the USP lookup to return a specific mood
		with patch("red_pill.utils.mystique.get_dominant_operator_mood", return_value="purple"):
			result = engine.suggest_skin(strategy="affinity", context="work", manager=manager)
			assert "name" in result
