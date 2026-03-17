"""
Surgical coverage tests targeting specific uncovered branches in memory.py.
Each test class maps to a code block identified in the coverage report.
"""

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from red_pill.memory import MemoryManager


@pytest.fixture
def cfg():
	c = SimpleNamespace(
		EMBEDDING_MODEL="test_model",
		DECAY_STRATEGY="exponential",
		DECAY_RATE=0.01,
		REINFORCEMENT_FACTOR=1.1,
		REINFORCEMENT_INCREMENT=0.05,
		MAX_AXONS=5,
		METABOLISM_STRATEGY="LAZY",
		METABOLISM_ENABLED=True,
		METABOLISM_COOLDOWN=60,
		ABSENCE_THRESHOLD=86400,
		ABSENCE_GUARD_SCROLL_LIMIT=1000,
		MAX_SINK_TIME=2592000,
		QDRANT_API_KEY="key",
		QDRANT_URL="http://localhost:6333",
		DEEP_RECALL_TRIGGERS=["matrix", "oracle"],
		PROPAGATION_FACTOR=0.5,
		PROPAGATION_DEPTH=2,
		PROPAGATION_DECAY=0.5,
		MAX_PROPAGATION_POINTS=100,
		EROSION_RATE=0.05,
		IMMUNITY_THRESHOLD=5.0,
		EMOTIONAL_SEED_FACTOR=0.2,
		CURRENT_SCHEMA_VERSION="6.0",
		METABOLISM_AUTO_COLLECTIONS=["work_memories"],
		MULTI_EMOTION_INFERENCE=True,
		DEFAULT_COLOR="blue",
		DEFAULT_EMOTION="neutral",
		CHUNK_THRESHOLD=100,
		DAEMON_SOCKET_PATH="/tmp/rp_test.sock",
		SIDECAR_AUTH_KEY="secret",
		EXECUTION_PROVIDER="cpu",
		METABOLISM_STATE_FILE="/tmp/meta_test.json",
		EMOTIONAL_DECAY_MULTIPLIERS={"blue": 1.0, "red": 2.0, "orange": 1.0, "neutral": 1.0, "joy": 0.8},
		BAYESIAN_COLLECTIONS=["skill_memories", "work_memories", "directive_memories"],
		BAYESIAN_STABILITY_KAPPA=0.05,
		BAYESIAN_REINFORCEMENT_GAIN=1.0,
		MEMORY_ENGINES={"work_memories": "bayesian", "social_memories": "fsrs_real"},
	)
	return c


@pytest.fixture
def mm(cfg):
	with patch("fastembed.TextEmbedding") as MockTE:
		with patch("red_pill.memory.QdrantClient"):
			with patch("red_pill.memory.HiveMind"):
				mock_enc = MagicMock()
				mock_enc.embed.return_value = [[0.1] * 384]
				MockTE.return_value = mock_enc
				mgr = MemoryManager(config=cfg)
				mgr.encoder = mock_enc
				mgr.client.get_collection.return_value = MagicMock(config=MagicMock(params=MagicMock(vectors=MagicMock(size=384))))  # type: ignore
				yield mgr


class TestAddMemoryBranches:
	def test_emotional_seed_scoring_applied(self, mm, cfg):
		"""Lines 241-244: high intensity + non-neutral emotion → seed bonus."""
		with patch("red_pill.memory.record_interaction"):
			result = mm.add_memory("work_memories", "intense emotional memory", emotion="joy", intensity=8.0, color="orange", importance=1.0)
		assert result != ""
		call_args = mm.client.upsert.call_args
		point = call_args[1]["points"][0]
		assert point.payload["reinforcement_score"] > 1.0

	def test_hive_transmit_called_for_work_memories(self, mm):
		"""Line 273: hive.transmit_experience called for non-immune work/social memories."""
		with patch("red_pill.memory.record_interaction"):
			mm.add_memory("work_memories", "technical finding", color="orange", emotion="joy")
		assert mm.hive.transmit_experience.called

	def test_hive_not_called_for_immune_memory(self, mm):
		"""Line 272: hive transmit skipped when force_immune=True."""
		mm.hive.transmit_experience.reset_mock()
		with patch("red_pill.memory.record_interaction"):
			mm.add_memory("work_memories", "immune content", force_immune=True)
		assert not mm.hive.transmit_experience.called

	def test_hive_not_called_for_story_collection(self, mm):
		"""Line 272: hive transmit skipped for non-work/social collections."""
		mm.hive.transmit_experience.reset_mock()
		with patch("red_pill.memory.record_interaction"):
			mm.add_memory("story_memories", "story content", color="orange", emotion="joy")
		assert not mm.hive.transmit_experience.called


class TestUpdateMemoryEdgeCases:
	def test_payload_none_returns_false(self, mm):
		"""Line 303-304: point exists but payload is None."""
		p = MagicMock()
		p.payload = None
		mm.client.retrieve.return_value = [p]
		assert mm.update_memory("work", "id1", color="red") is False

	def test_no_fields_to_update_returns_true(self, mm):
		"""Line 314: update_payload is empty, still returns True."""
		p = MagicMock()
		p.payload = {"color": "blue"}
		mm.client.retrieve.return_value = [p]
		result = mm.update_memory("work", "id1")
		assert result is True
		assert not mm.client.set_payload.called


class TestTriggerMetabolism:
	def test_skips_if_thread_alive(self, mm):
		"""Lines 323-324: returns early if thread already running."""
		alive_thread = MagicMock()
		alive_thread.is_alive.return_value = True
		mm._metabolism_thread = alive_thread
		mm._trigger_metabolism()
		assert mm._metabolism_thread is alive_thread

	def test_thread_launch_exception_caught(self, mm):
		"""Lines 329-330: exception during thread creation is logged, not raised."""
		with patch("threading.Thread", side_effect=RuntimeError("No threads")):
			mm._trigger_metabolism()


class TestMetabolismCycleBranches:
	def test_ttl_refresh_exception_logged(self, mm, cfg):
		"""Lines 416-417: exception in _refresh_ttl_timestamps is caught per-collection."""
		state = json.dumps({"last_run": time.time() - 300000, "skip_next_erosion": False})
		with patch("builtins.open", mock_open(read_data=state)):
			with patch("fcntl.flock"):
				with patch("os.path.exists", return_value=True):
					with patch.object(mm, "_refresh_ttl_timestamps", side_effect=Exception("TTL boom")):
						mm._run_metabolism_cycle()

	def test_skip_next_erosion_flag_consumed(self, mm, cfg):
		"""Lines 427-435: when skip_next_erosion=True, cycle returns early and clears flag."""
		state = json.dumps({"last_run": time.time() - 7200, "skip_next_erosion": True})
		with patch("builtins.open", mock_open(read_data=state)):
			with patch("fcntl.flock"):
				with patch("os.path.exists", return_value=True):
					with patch.object(mm, "_write_metabolism_state") as mock_write:
						mm._run_metabolism_cycle()
						assert mock_write.called
						call_kwargs = mock_write.call_args
						assert call_kwargs.kwargs.get("skip_next_erosion") is False or call_kwargs.args[-1] is False

	def test_apply_erosion_strategy_when_not_lazy(self, mm, cfg):
		"""Lines 447-450: METABOLISM_STRATEGY != LAZY → apply_erosion called instead."""
		cfg.METABOLISM_STRATEGY = "EAGER"
		state = json.dumps({"last_run": time.time() - 7200, "skip_next_erosion": False})
		with patch("builtins.open", mock_open(read_data=state)):
			with patch("fcntl.flock"):
				with patch("os.path.exists", return_value=True):
					with patch.object(mm, "apply_erosion") as mock_erosion:
						with patch.object(mm, "purge_dead_memories") as mock_purge:
							mm._run_metabolism_cycle()
							assert mock_erosion.called
							assert not mock_purge.called

	def test_oserror_in_state_file_caught(self, mm):
		"""Lines 442-443: OSError when opening state file is swallowed."""
		with patch("builtins.open", side_effect=OSError("No file")):
			with patch("os.path.exists", return_value=True):
				with patch.object(mm, "purge_dead_memories") as mock_purge:
					mm._run_metabolism_cycle()
					assert mock_purge.called


class TestRefreshTTLBranches:
	def test_scroll_exception_breaks_loop(self, mm):
		"""Lines 497-499: scroll failure during TTL refresh is logged and loop breaks."""
		mm.client.scroll.side_effect = Exception("scroll boom")
		mm._refresh_ttl_timestamps("work")

	def test_set_payload_exception_caught(self, mm):
		"""Lines 503-507: set_payload failure during TTL refresh is logged."""
		p1 = MagicMock(id="1")
		mm.client.scroll.return_value = ([p1], None)
		mm.client.set_payload.side_effect = Exception("payload boom")
		mm._refresh_ttl_timestamps("work")


class TestReinforcePointsBranches:
	def test_invalid_uuid_skipped(self, mm):
		"""Lines 531-535: non-UUID string is skipped from valid_ids."""
		mm.client.retrieve.return_value = []
		result = mm._reinforce_points("work", ["not-a-uuid", "also-bad!!"], {})
		assert result == []
		mm.client.retrieve.assert_called_once_with(collection_name="work", ids=[], with_payload=True, with_vectors=False)

	def test_retrieve_exception_returns_empty(self, mm):
		"""Lines 540-542: retrieve exception → returns []."""
		mm.client.retrieve.side_effect = Exception("db down")
		result = mm._reinforce_points("work", [str(uuid.uuid4())], {})
		assert result == []


class TestSearchAndReinforceErrors:
	def test_query_points_exception_returns_empty(self, mm):
		"""Lines 610-612: query_points failure → returns []."""
		mm.client.query_points.side_effect = Exception("Qdrant down")
		result = mm.search_and_reinforce("work", "query")
		assert result == []


class TestSearchLazyDecayBranches:
	def test_lazy_decay_to_zero_triggers_delete(self, mm, cfg):
		"""Lines 630-637: score decays to 0 → point deleted from Qdrant."""
		cfg.METABOLISM_STRATEGY = "LAZY"
		p1 = MagicMock(
			id="1",
			payload={"reinforcement_score": 0.001, "last_recalled_at": time.time() - 500000, "emotion": "neutral", "intensity": 1.0, "immune": False},
		)
		mm.client.query_points.return_value = MagicMock(points=[p1])
		mm.search_and_reinforce("work", "query")
		assert mm.client.delete.called

	def test_lazy_decay_partial_syncs_score(self, mm, cfg):
		"""Lines 639-645: score decays but > 0 → batch sync to Qdrant."""
		cfg.METABOLISM_STRATEGY = "LAZY"
		cfg.DECAY_STRATEGY = "exponential"
		cfg.DECAY_RATE = 0.1
		p1 = MagicMock(
			id="1",
			payload={"reinforcement_score": 0.5, "last_recalled_at": time.time() - 500000, "emotion": "neutral", "intensity": 1.0, "immune": False},
		)
		mm.client.query_points.return_value = MagicMock(points=[p1])
		mm.client.retrieve.return_value = []
		with patch.object(mm, "_calculate_lazy_decay", return_value=0.3):
			mm.search_and_reinforce("work", "query")
		assert mm.client.batch_update_points.called

	def test_lazy_decay_batch_sync_exception_caught(self, mm, cfg):
		"""Lines 651-654: batch_update after lazy sync fails → logged, not raised."""
		cfg.METABOLISM_STRATEGY = "LAZY"
		p1 = MagicMock(id="1", payload={"reinforcement_score": 1.0, "last_recalled_at": time.time() - 500000, "emotion": "neutral", "intensity": 1.0})
		mm.client.query_points.return_value = MagicMock(points=[p1])
		mm.client.retrieve.return_value = []
		mm.client.batch_update_points.side_effect = Exception("batch boom")
		mm.search_and_reinforce("work", "query")

	def test_payload_none_skipped_in_search(self, mm, cfg):
		"""Line 624: hits with None payload are skipped."""
		cfg.METABOLISM_STRATEGY = "LAZY"
		p1 = MagicMock(id="1")
		p1.payload = None
		mm.client.query_points.return_value = MagicMock(points=[p1])
		result = mm.search_and_reinforce("work", "query")
		assert result == []


class TestNHopPropagation:
	def test_depth_2_retrieval_called(self, mm, cfg):
		"""Lines 678-686: depth=2 triggers retrieve for the second ring."""
		cfg.PROPAGATION_DEPTH = 2
		h1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "associations": ["2"]})
		mm.client.query_points.return_value = MagicMock(points=[h1])
		h2 = MagicMock(id="2", payload={"associations": ["3"], "reinforcement_score": 0.5})
		h3 = MagicMock(id="3", payload={"associations": [], "reinforcement_score": 0.5})
		mm.client.retrieve.side_effect = [[h2], [h3]]
		mm.search_and_reinforce("work", "query deep", deep_recall=True)
		assert mm.client.retrieve.call_count >= 1

	def test_depth_2_retrieve_exception_breaks_loop(self, mm, cfg):
		"""Lines 688-690: exception at depth > 1 is caught and loop breaks."""
		cfg.PROPAGATION_DEPTH = 2
		h1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "associations": ["2"]})
		mm.client.query_points.return_value = MagicMock(points=[h1])
		h2 = MagicMock(id="2", payload={"associations": ["3"], "reinforcement_score": 0.5})
		mm.client.retrieve.side_effect = [[h2], Exception("hop boom")]
		mm.search_and_reinforce("work", "query", deep_recall=True)


class TestErosionSkipBranches:
	def test_none_payload_skipped(self, mm):
		"""Line 868-869: points with None payload are skipped."""
		p1 = MagicMock(id="1")
		p1.payload = None
		mm.client.scroll.side_effect = [([p1], None)]
		mm.apply_erosion("work", rate=0.1)
		assert not mm.client.delete.called
		assert not mm.client.batch_update_points.called

	def test_immune_point_skipped(self, mm):
		"""Lines 872-873: immune points survive erosion."""
		p1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "immune": True, "emotion": "neutral"})
		mm.client.scroll.side_effect = [([p1], None)]
		mm.apply_erosion("work", rate=0.1)
		assert not mm.client.delete.called

	def test_erosion_delete_exception_caught(self, mm):
		"""Lines 913-915: delete failure after erosion is caught."""
		p1 = MagicMock(id="1", payload={"reinforcement_score": 0.001, "emotion": "neutral"})
		mm.client.scroll.side_effect = [([p1], None)]
		mm.client.delete.side_effect = Exception("delete boom")
		mm.apply_erosion("work", rate=0.5)

	def test_erosion_batch_update_exception_caught(self, mm):
		"""Lines 908-909: batch update failure after erosion is caught."""
		p1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "emotion": "neutral"})
		mm.client.scroll.side_effect = [([p1], None)]
		mm.client.batch_update_points.side_effect = Exception("batch boom")
		mm.apply_erosion("work", rate=0.01)


class TestSanitizeBranches:
	def test_scroll_exception_breaks_loop(self, mm):
		"""Lines 945-947: scroll failure → loop breaks."""
		mm.client.scroll.side_effect = Exception("scroll boom")
		result = mm.sanitize("work")
		assert result["duplicates_found"] == 0

	def test_none_payload_skipped(self, mm):
		"""Line 952-953: points with None payload are skipped."""
		p1 = MagicMock(id="1")
		p1.payload = None
		mm.client.scroll.return_value = ([p1], None)
		result = mm.sanitize("work")
		assert result["migrated_records"] == 0

	def test_batch_update_exception_caught(self, mm):
		"""Lines 989-990: migration batch update failure is caught."""
		p1 = MagicMock(id="1", payload={"content": "c", "schema_version": "1.0"})
		mm.client.scroll.return_value = ([p1], None)
		mm.client.batch_update_points.side_effect = Exception("batch boom")
		mm.sanitize("work")

	def test_dry_run_skips_writes(self, mm):
		"""Line 983-984: dry_run=True skips batch_update and delete."""
		p1 = MagicMock(id="1", payload={"content": "c1", "schema_version": "1.0"})
		p2 = MagicMock(id="2", payload={"content": "c1"})
		mm.client.scroll.return_value = ([p1, p2], None)
		result = mm.sanitize("work", dry_run=True)
		assert result["dry_run"] is True
		assert result["duplicates_found"] == 1
		assert not mm.client.batch_update_points.called
		assert not mm.client.delete.called

	def test_duplicate_delete_exception_caught(self, mm):
		"""Lines 1006-1007: deletion failure for duplicates is caught."""
		p1 = MagicMock(id="1", payload={"content": "dup", "schema_version": "6.0", "color": "blue", "emotion": "neutral", "intensity": 1.0})
		p2 = MagicMock(id="2", payload={"content": "dup"})
		mm.client.scroll.return_value = ([p1, p2], None)
		mm.client.delete.side_effect = Exception("delete boom")
		mm.sanitize("work")


class TestGetStatsBranches:
	def test_exception_returns_error_dict(self, mm):
		"""Lines 1020-1022: get_collection raises → returns error dict."""
		mm.client.get_collection.side_effect = Exception("Qdrant down")
		result = mm.get_stats("work")
		assert result["status"] == "error"
		assert result["points_count"] == 0
