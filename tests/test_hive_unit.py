"""Tests for red_pill/hive.py — targeting all uncovered branches.

Missing lines:
	8-9   : pymilvus ImportError fallback
	46-61 : connections.connect() full remote path + exception
	110-136: _agentic_know_how_review() — short content, LLM KNOW-HOW/NOISE, exception, fallback heuristic
	149-150: _mask_identity_signals() — op_name masking
	166, 170, 177: transmit_experience() — not connected, smith filter blocked, collection creation
	192-205: _create_hive_collection() — schema definition + index
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_milvus():
	with (
		patch("red_pill.hive.connections") as mock_conn,
		patch("red_pill.hive.Collection") as mock_coll,
		patch("red_pill.hive.utility") as mock_util,
		patch("red_pill.hive.CollectionSchema") as mock_schema,
		patch("red_pill.hive.FieldSchema") as mock_field,
		patch("red_pill.hive.DataType") as mock_dtype,
	):
		yield {"conn": mock_conn, "coll": mock_coll, "util": mock_util, "schema": mock_schema, "field": mock_field, "dtype": mock_dtype}


def _make_hive(connected=True, mock_milvus=None):
	from red_pill.hive import HiveMind

	hive = HiveMind.__new__(HiveMind)
	hive.enabled = True
	hive.connected = connected
	return hive


def test_hive_connection_error(mock_milvus):
	"""Test handling of connection failures."""
	mock_milvus["conn"].connect.side_effect = Exception("No Milvus here")
	from red_pill.hive import HiveMind

	hive = HiveMind()
	assert hive.connected is False


def test_transmit_experience_failure(mock_milvus):
	"""Test transmission failures."""
	mock_milvus["util"].has_collection.side_effect = Exception("DB dead")
	from red_pill.hive import HiveMind

	hive = HiveMind.__new__(HiveMind)
	hive.enabled = True
	hive.connected = True
	hive.transmit_experience("work_memories", "breakthrough", [0.1] * 384, {})


def test_sync_from_hive_empty(mock_milvus):
	"""Test sync when collection doesn't exist."""
	mock_milvus["util"].has_collection.return_value = False
	from red_pill.hive import HiveMind

	hive = HiveMind.__new__(HiveMind)
	hive.enabled = True
	hive.connected = True
	assert hive.sync_from_hive([0.1] * 384, "hive_work") == []


def test_sync_from_hive_error(mock_milvus):
	"""Test sync failure handling."""
	mock_milvus["util"].has_collection.return_value = True
	mock_milvus["coll"].return_value.search.side_effect = Exception("Search error")
	from red_pill.hive import HiveMind

	hive = HiveMind.__new__(HiveMind)
	hive.enabled = True
	hive.connected = True
	assert hive.sync_from_hive([0.1] * 384, "hive_work") == []


class TestPymilvusImportFallback:
	def test_connections_none_when_pymilvus_missing(self):
		"""Lines 8-9: ImportError → connections = None."""
		original = sys.modules.pop("red_pill.hive", None)
		pymilvus_modules = {k: v for k, v in list(sys.modules.items()) if "pymilvus" in k}
		for k in pymilvus_modules:
			sys.modules.pop(k, None)
		try:
			sys.modules["pymilvus"] = None  # type: ignore
			import importlib

			import red_pill.hive as hive_mod

			importlib.reload(hive_mod)
			assert hasattr(hive_mod, "connections")
		except Exception:
			pass
		finally:
			sys.modules.pop("pymilvus", None)
			if original is not None:
				sys.modules["red_pill.hive"] = original
			for k, v in pymilvus_modules.items():
				sys.modules[k] = v


class TestHiveMindInit:
	def test_remote_secure_connection_succeeds(self, mock_milvus):
		"""Lines 46-56: remote host + secure=True → connections.connect() called."""
		with (
			patch("red_pill.config.MILVUS_ENABLED", True),
			patch("red_pill.config.MILVUS_HOST", "remote.milvus.io"),
			patch("red_pill.config.MILVUS_SECURE", True),
			patch("red_pill.config.MILVUS_LITE_ENABLED", False),
		):
			from red_pill.hive import HiveMind

			hive = HiveMind()
		assert hive.connected is True
		mock_milvus["conn"].connect.assert_called_once()

	def test_remote_insecure_blocked(self, mock_milvus):
		"""Lines 41-44: remote + not secure → blocked, connected=False."""
		with (
			patch("red_pill.config.MILVUS_ENABLED", True),
			patch("red_pill.config.MILVUS_HOST", "remote.milvus.io"),
			patch("red_pill.config.MILVUS_SECURE", False),
			patch("red_pill.config.MILVUS_LITE_ENABLED", False),
		):
			from red_pill.hive import HiveMind

			hive = HiveMind()
		assert hive.connected is False
		mock_milvus["conn"].connect.assert_not_called()

	def test_lite_local_connection(self, mock_milvus):
		"""Lines 35-39: Milvus Lite + local → connect with uri."""
		with (
			patch("red_pill.config.MILVUS_ENABLED", True),
			patch("red_pill.config.MILVUS_HOST", "localhost"),
			patch("red_pill.config.MILVUS_LITE_ENABLED", True),
			patch("red_pill.config.MILVUS_LITE_PATH", "/tmp/test_hive.db"),
		):
			from red_pill.hive import HiveMind

			hive = HiveMind()
		assert hive.connected is True
		mock_milvus["conn"].connect.assert_called_once_with(alias="default", uri="/tmp/test_hive.db")

	def test_disabled_hive_not_connected(self):
		"""Lines 25-27: MILVUS_ENABLED=False → connected=False."""
		with patch("red_pill.config.MILVUS_ENABLED", False):
			from red_pill.hive import HiveMind

			hive = HiveMind()
		assert hive.connected is False


class TestAgenticKnowHowReview:
	def test_short_content_rejected(self):
		"""Line 107-108: content < 30 chars → False."""
		hive = _make_hive()
		assert hive._agentic_know_how_review("short") is False

	def test_llm_know_how_response(self):
		"""Lines 121-125: LLM returns KNOW-HOW → True."""
		hive = _make_hive()
		mock_engine = MagicMock()
		mock_engine.model_path = "/fake/model.gguf"
		mock_engine.synthesize.return_value = "KNOW-HOW: this is a reusable directive"
		with patch("red_pill.hive.EdgeEngine", return_value=mock_engine):
			with patch("os.path.exists", return_value=True):
				result = hive._agentic_know_how_review("Always prefer explicit imports over wildcard imports in Python.")
		assert result is True

	def test_llm_noise_response(self):
		"""Lines 126-128: LLM returns NOISE → False."""
		hive = _make_hive()
		mock_engine = MagicMock()
		mock_engine.model_path = "/fake/model.gguf"
		mock_engine.synthesize.return_value = "NOISE: personal chatter"
		with patch("red_pill.hive.EdgeEngine", return_value=mock_engine):
			with patch("os.path.exists", return_value=True):
				result = hive._agentic_know_how_review("Joan said he liked his coffee this morning.")
		assert result is False

	def test_llm_exception_falls_back_to_heuristic(self):
		"""Lines 129-136: LLM raises → fallback heuristic."""
		hive = _make_hive()
		mock_engine = MagicMock()
		mock_engine.model_path = "/fake/model.gguf"
		mock_engine.synthesize.side_effect = RuntimeError("GPU dead")
		with patch("red_pill.hive.EdgeEngine", return_value=mock_engine):
			with patch("os.path.exists", return_value=True):
				result = hive._agentic_know_how_review("Always use type hints in Python code for clarity.")
		assert result is True

	def test_no_model_path_uses_heuristic(self):
		"""Lines 132-136: no model path → fallback heuristic directly."""
		hive = _make_hive()
		mock_engine = MagicMock()
		mock_engine.model_path = None
		with patch("red_pill.hive.EdgeEngine", return_value=mock_engine):
			result = hive._agentic_know_how_review("prefer explicit configuration over implicit defaults always.")
		assert result is True

	def test_heuristic_fails_on_generic_content(self):
		"""Lines 132-136: fallback heuristic → no markers → False."""
		hive = _make_hive()
		mock_engine = MagicMock()
		mock_engine.model_path = None
		with patch("red_pill.hive.EdgeEngine", return_value=mock_engine):
			result = hive._agentic_know_how_review("The user went to the store to buy some milk and eggs.")
		assert result is False


class TestMaskIdentitySignals:
	def test_masks_operator_name(self):
		"""Lines 147-150: op_name in content → replaced with [Operator]."""
		hive = _make_hive()
		with patch("red_pill.config.OPERATOR_DISPLAY_NAME", "Joan"):
			result = hive._mask_identity_signals("Joan prefers dark mode always.")
		assert "Joan" not in result
		assert "[Operator]" in result

	def test_masks_first_person_yo(self):
		"""Line 156: 'yo ' at start → replaced with [Operator]."""
		hive = _make_hive()
		with patch("red_pill.config.OPERATOR_DISPLAY_NAME", ""):
			result = hive._mask_identity_signals("yo prefiero usar tabs.")
		assert result.startswith("[Operator]")

	def test_no_masking_when_name_is_operator(self):
		"""Lines 147: op_name == 'operator' → no replacement."""
		hive = _make_hive()
		with patch("red_pill.config.OPERATOR_DISPLAY_NAME", "operator"):
			result = hive._mask_identity_signals("operator is the default name.")
		assert result == "operator is the default name."


class TestTransmitExperience:
	def test_not_connected_returns_early(self):
		"""Line 166: not connected → early return."""
		hive = _make_hive(connected=False)
		hive.transmit_experience("work_memories", "content", [0.1] * 384, {})

	def test_smith_filter_blocks_transmission(self, mock_milvus):
		"""Line 170: smith filter returns False → return."""
		hive = _make_hive(connected=True)
		with patch.object(hive, "_passes_smith_filter", return_value=False):
			hive.transmit_experience("work_memories", "api_key=secret123", [0.1] * 384, {})
		mock_milvus["util"].has_collection.assert_not_called()

	def test_successful_transmission_creates_collection(self, mock_milvus):
		"""Lines 173-186: filter passes + collection missing → create + insert."""
		mock_milvus["util"].has_collection.return_value = False
		mock_col = MagicMock()
		mock_milvus["coll"].return_value = mock_col
		hive = _make_hive(connected=True)
		with patch.object(hive, "_passes_smith_filter", return_value=True):
			with patch.object(hive, "_mask_identity_signals", return_value="masked content"):
				with patch.object(hive, "_create_hive_collection") as mock_create:
					hive.transmit_experience("work_memories", "good content", [0.1] * 384, {})
		mock_create.assert_called_once_with("work_memories")
		mock_col.insert.assert_called_once()
		mock_col.flush.assert_called_once()

	def test_transmission_existing_collection(self, mock_milvus):
		"""Line 177: collection exists → no create, direct insert."""
		mock_milvus["util"].has_collection.return_value = True
		mock_col = MagicMock()
		mock_milvus["coll"].return_value = mock_col
		hive = _make_hive(connected=True)
		with patch.object(hive, "_passes_smith_filter", return_value=True):
			with patch.object(hive, "_mask_identity_signals", return_value="masked"):
				hive.transmit_experience("work_memories", "good knowledge", [0.1] * 384, {"importance": 5.0})
		mock_col.insert.assert_called_once()


class TestCreateHiveCollection:
	def test_creates_schema_and_index(self, mock_milvus):
		"""Lines 192-205: field definitions + schema + collection + index."""
		mock_col = MagicMock()
		mock_milvus["coll"].return_value = mock_col
		hive = _make_hive(connected=True)
		hive._create_hive_collection("test_sector")
		mock_milvus["coll"].assert_called_once()
		mock_col.create_index.assert_called_once()
		mock_col.load.assert_called_once()


class TestPassesSmithFilter:
	def test_non_work_non_social_blocked(self):
		"""Line 73-74: not work/social collection → False."""
		hive = _make_hive()
		result = hive._passes_smith_filter("directive_memories", "some content", {})
		assert result is False

	def test_email_pii_blocked(self):
		"""Lines 83-86: email pattern → False."""
		hive = _make_hive()
		result = hive._passes_smith_filter("work_memories", "contact: user@example.com", {})
		assert result is False

	def test_phone_number_blocked(self):
		"""Lines 83-86: phone number pattern → False."""
		hive = _make_hive()
		result = hive._passes_smith_filter("work_memories", "call me +34 612 345 6789", {})
		assert result is False

	def test_immune_engram_blocked(self):
		"""Lines 95-96: immune=True → False."""
		hive = _make_hive()
		with patch.object(hive, "_agentic_know_how_review", return_value=True):
			result = hive._passes_smith_filter("social_memories", "clean content for humans", {"immune": True})
		assert result is False

	def test_clean_work_content_passes(self):
		"""Line 98: clean work content → True."""
		hive = _make_hive()
		result = hive._passes_smith_filter("work_memories", "Always use explicit imports in Python.", {})
		assert result is True


class TestSyncFromHive:
	def test_sync_returns_experiences(self, mock_milvus):
		"""Lines 222-233: search returns hits → structured results."""
		mock_milvus["util"].has_collection.return_value = True
		mock_hit = MagicMock()
		mock_hit.entity.get.side_effect = lambda k: {"content": "know-how", "source_agent": "agent-1", "importance": 5.0}.get(k)
		mock_hit.distance = 0.12
		mock_col = MagicMock()
		mock_col.search.return_value = [[mock_hit]]
		mock_milvus["coll"].return_value = mock_col
		hive = _make_hive(connected=True)
		results = hive.sync_from_hive([0.1] * 384, "hive_work")
		assert len(results) == 1
		assert results[0]["content"] == "know-how"
		assert results[0]["distance"] == 0.12
