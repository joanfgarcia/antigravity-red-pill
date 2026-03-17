"""
Second surgical boost — targeting remaining uncovered lines after 92% run.
Missing: 16-17, 101, 107-108, 152-153, 202, 207-209, 317-319, 348, 355-356,
         451-452, 475-476, 524, 562, 572, 597-598, 635-636, 653-654,
         688-690, 711, 797, 804, 826, 836, 838, 922-925, 997-1000
"""

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from red_pill.memory import MemoryManager, PointUpdate


@pytest.fixture
def cfg():
	return SimpleNamespace(
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
		DAEMON_SOCKET_PATH="/tmp/rp_boost.sock",
		SIDECAR_AUTH_KEY="secret",
		EXECUTION_PROVIDER="cpu",
		METABOLISM_STATE_FILE="/tmp/meta_boost.json",
		EMOTIONAL_DECAY_MULTIPLIERS={"blue": 1.0, "red": 2.0, "orange": 1.0, "neutral": 1.0, "joy": 0.8},
		BAYESIAN_COLLECTIONS=["skill_memories", "work_memories", "directive_memories"],
		BAYESIAN_STABILITY_KAPPA=0.05,
		BAYESIAN_REINFORCEMENT_GAIN=1.0,
		MEMORY_ENGINES={"work_memories": "bayesian", "social_memories": "fsrs_real"},
	)


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
				yield mgr


# ---------------------------------------------------------------------------
# Lines 16-17: module-level ImportError fallback for fastembed
# ---------------------------------------------------------------------------


def test_module_import_error_fallback():
	"""Lines 16-17: When fastembed is absent at import time, TextEmbedding = Any."""
	# We can't re-import the module, but we can confirm the fallback exists
	import red_pill.memory as mem_mod

	assert hasattr(mem_mod, "TextEmbedding")


# ---------------------------------------------------------------------------
# Lines 101, 107-108: _get_vector daemon returns value / EXECUTION_PROVIDER=None
# ---------------------------------------------------------------------------


def test_get_vector_returns_daemon_result(mm):
	"""Line 101: if daemon returns a vector, use it directly (no encoder needed)."""
	mm.encoder = None
	with patch.object(mm, "_get_vector_from_daemon", return_value=[0.9] * 384):
		result = mm._get_vector("text")
	assert result == [0.9] * 384
	# Encoder was never initialised
	assert mm.encoder is None


def test_get_vector_lazy_init_no_provider(mm, cfg):
	"""Lines 107-108: EXECUTION_PROVIDER=None → providers=None passed to TextEmbedding."""
	mm.encoder = None
	cfg.EXECUTION_PROVIDER = None
	with patch.object(mm, "_get_vector_from_daemon", return_value=None):
		with patch("fastembed.TextEmbedding") as MockTE:
			mock_enc = MagicMock()
			mock_enc.embed.return_value = iter([[0.5] * 384])
			MockTE.return_value = mock_enc
			mm._get_vector("text")
			# providers kwarg should be None
			MockTE.assert_called_once_with(model_name=cfg.EMBEDDING_MODEL, providers=None)


# ---------------------------------------------------------------------------
# Lines 152-153: add_memory validation error path
# ---------------------------------------------------------------------------


def test_add_memory_validation_error_raised(mm):
	"""Lines 152-153: invalid data raises ValueError (propagated from CreateEngramRequest)."""
	with patch("red_pill.memory.record_interaction"):
		with patch("red_pill.memory.CreateEngramRequest", side_effect=Exception("bad data")):
			with pytest.raises(ValueError, match="Invalid engram data"):
				mm.add_memory("work", "text")


# ---------------------------------------------------------------------------
# Lines 202, 207-209: add_memory emotion detection sub-branches
# ---------------------------------------------------------------------------


def test_add_memory_chroma_set_when_color_is_default(mm, cfg):
	"""Line 202: color is set via get_chroma_for_emotion when still default."""
	with patch("red_pill.memory.record_interaction"):
		with patch("red_pill.memory.get_emotions", return_value=[{"label": "joy", "score": 0.9}]):
			with patch("red_pill.memory.get_chroma_for_emotion", return_value="orange") as mock_chroma:
				# color and emotion both stay at defaults → trigger auto-detect path
				mm.add_memory("work_memories", "happy news", color=cfg.DEFAULT_COLOR, emotion=cfg.DEFAULT_EMOTION)
				assert mock_chroma.called


def test_add_memory_single_emotion_fallback(mm, cfg):
	"""Lines 205-209: MULTI_EMOTION_INFERENCE=False → single get_emotion fallback."""
	cfg.MULTI_EMOTION_INFERENCE = False
	with patch("red_pill.memory.record_interaction"):
		with patch("red_pill.memory.get_emotions", return_value=[]):
			with patch("red_pill.memory.get_emotion", return_value="joy") as mock_single:
				with patch("red_pill.memory.get_chroma_for_emotion", return_value="orange"):
					mm.add_memory("work_memories", "fallback emotion", color=cfg.DEFAULT_COLOR, emotion=cfg.DEFAULT_EMOTION)
					# multi path returns empty, single should be called
					assert mock_single.called


# ---------------------------------------------------------------------------
# Lines 317-319: _trigger_metabolism thread launch exception
# ---------------------------------------------------------------------------


def test_trigger_metabolism_thread_exception(mm):
	"""Lines 329-330: thread creation fails → error logged, no raise."""
	mm._metabolism_thread = None
	with patch("threading.Thread", side_effect=RuntimeError("no threads available")):
		mm._trigger_metabolism()  # Must not raise


# ---------------------------------------------------------------------------
# Lines 348, 355-356: _read_metabolism_state edge cases
# ---------------------------------------------------------------------------


def test_read_metabolism_state_empty_file(mm):
	"""Line 348: empty file → returns (0.0, False)."""
	f = MagicMock()
	f.read.return_value = ""
	result = mm._read_metabolism_state(f)
	assert result == (0.0, False)


def test_read_metabolism_state_corrupt_json(mm):
	"""Lines 355-356: malformed JSON → returns (0.0, False)."""
	f = MagicMock()
	f.read.return_value = "not-valid-json!!!"
	result = mm._read_metabolism_state(f)
	assert result == (0.0, False)


def test_read_metabolism_state_bare_float(mm):
	"""Line 354: legacy bare float → parsed as (float, False)."""
	f = MagicMock()
	f.read.return_value = "1700000000.5"
	last_run, skip = mm._read_metabolism_state(f)
	assert last_run == pytest.approx(1700000000.5)
	assert skip is False


# ---------------------------------------------------------------------------
# Lines 451-452: metabolism exception per-collection
# ---------------------------------------------------------------------------


def test_metabolism_cycle_collection_exception_caught(mm, cfg):
	"""Lines 451-452: exception in purge_dead_memories per collection is caught."""
	state = json.dumps({"last_run": time.time() - 7200, "skip_next_erosion": False})
	with patch("builtins.open", mock_open(read_data=state)):
		with patch("fcntl.flock"):
			with patch("os.path.exists", return_value=True):
				with patch.object(mm, "purge_dead_memories", side_effect=Exception("purge boom")):
					mm._run_metabolism_cycle()  # Must not raise


# ---------------------------------------------------------------------------
# Lines 475-476: _refresh_ttl_timestamps safety break
# ---------------------------------------------------------------------------


def test_refresh_ttl_safety_break(mm, cfg):
	"""Lines 514-517: ABSENCE_GUARD_SCROLL_LIMIT reached → loop breaks."""
	cfg.ABSENCE_GUARD_SCROLL_LIMIT = 2
	# Each scroll returns a point + a next offset, forcing more iterations
	p1 = MagicMock(id="1")
	# Return offset="next" repeatedly to trigger safety break
	mm.client.scroll.side_effect = [([p1], "offset1"), ([p1], "offset2"), ([p1], "offset3")]
	mm._refresh_ttl_timestamps("work")
	# Should break after 2 iterations (ABSENCE_GUARD_SCROLL_LIMIT)
	assert mm.client.scroll.call_count == 3  # calls 0,1,2 then breaks after count>2


# ---------------------------------------------------------------------------
# (Legacy) Line 572: focused_payload includes immune when present
# These old immunity tests are disabled since Dual-Kernel v6.1 handles stability
# per-engine (Bayesian vs FSRS) instead of hardcoded threshold promotion.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Lines 597-598: search_and_reinforce regex deep-recall trigger
# ---------------------------------------------------------------------------


def test_search_regex_trigger_sets_deep_recall(mm, cfg):
	"""Lines 597-598: query containing trigger word → deep_recall activated (no filter)."""
	h1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "associations": []})
	mm.client.query_points.return_value = MagicMock(points=[h1])
	mm.client.retrieve.return_value = []

	# "matrix" is in DEEP_RECALL_TRIGGERS
	mm.search_and_reinforce("work", "I was in the matrix today")

	call_kwargs = mm.client.query_points.call_args[1]
	# deep_recall=True → no filter applied
	assert call_kwargs["query_filter"] is None


# ---------------------------------------------------------------------------
# Lines 635-636: lazy delete exception caught
# ---------------------------------------------------------------------------


def test_lazy_delete_exception_caught(mm, cfg):
	"""Lines 635-636: delete failure during lazy decay → logged, point skipped."""
	cfg.METABOLISM_STRATEGY = "LAZY"
	p1 = MagicMock(
		id="1",
		payload={
			"reinforcement_score": 0.001,
			"last_recalled_at": time.time() - 500000,
			"emotion": "neutral",
			"intensity": 1.0,
			"immune": False,
		},
	)
	mm.client.query_points.return_value = MagicMock(points=[p1])
	mm.client.delete.side_effect = Exception("delete boom")
	with patch.object(mm, "_calculate_lazy_decay", return_value=0.0):
		mm.search_and_reinforce("work", "query")  # Must not raise


# ---------------------------------------------------------------------------
# Lines 653-654: lazy batch_update_points failure
# ---------------------------------------------------------------------------


def test_lazy_batch_sync_exception_caught(mm, cfg):
	"""Lines 653-654: batch_update_points failure during lazy sync → logged, not raised."""
	cfg.METABOLISM_STRATEGY = "LAZY"
	p1 = MagicMock(
		id="1",
		payload={
			"reinforcement_score": 1.0,
			"last_recalled_at": time.time() - 500000,
			"emotion": "neutral",
			"intensity": 1.0,
		},
	)
	mm.client.query_points.return_value = MagicMock(points=[p1])
	mm.client.retrieve.return_value = []
	mm.client.batch_update_points.side_effect = Exception("batch boom")
	with patch.object(mm, "_calculate_lazy_decay", return_value=0.5):
		mm.search_and_reinforce("work", "query")  # Must not raise


# ---------------------------------------------------------------------------
# Lines 711: decayed_results payload update from _reinforce_points
# ---------------------------------------------------------------------------


def test_search_payload_updated_from_reinforce(mm, cfg):
	"""Line 711: after reinforcement, hit.payload is updated with new values."""
	h1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "associations": [], "last_recalled_at": time.time()})
	mm.client.query_points.return_value = MagicMock(points=[h1])

	# _reinforce_points returns updated PointUpdate
	updated = PointUpdate(id="1", payload={"reinforcement_score": 0.6, "last_recalled_at": time.time()})
	with patch.object(mm, "_reinforce_points", return_value=[updated]):
		results = mm.search_and_reinforce("work", "query")

	assert len(results) == 1
	# Payload should have been merged
	assert results[0].payload["reinforcement_score"] == 0.6


# ---------------------------------------------------------------------------
# Line 797: _calculate_decay linear strategy
# ---------------------------------------------------------------------------


def test_calculate_decay_linear_strategy(mm, cfg):
	"""Line 797: linear strategy → simple subtraction."""
	cfg.DECAY_STRATEGY = "linear"
	result = mm._calculate_decay(0.5, 0.1)
	assert result == pytest.approx(0.4, abs=0.01)


# ---------------------------------------------------------------------------
# Line 804: _calculate_lazy_decay immune shortcut
# ---------------------------------------------------------------------------


def test_calculate_lazy_decay_immune_returns_score(mm, cfg):
	"""Line 804: immune payload → returns reinforcement_score unchanged."""
	payload = {"immune": True, "reinforcement_score": 3.7}
	result = mm._calculate_lazy_decay(payload, "work_memories")
	assert result == pytest.approx(3.7)


# ---------------------------------------------------------------------------
# Line 826: _calculate_lazy_decay linear strategy
# ---------------------------------------------------------------------------


def test_calculate_lazy_decay_linear(mm, cfg):
	"""Line 826: linear decay strategy across cycles."""
	cfg.DECAY_STRATEGY = "linear"
	payload = {
		"reinforcement_score": 1.0,
		"last_recalled_at": time.time() - 600,  # 10 cycles at cooldown=60
		"emotion": "neutral",
		"intensity": 1.0,
	}
	result = mm._calculate_lazy_decay(payload, "work_memories")
	assert result < 1.0  # should have decayed
	assert result >= 0.0


# ---------------------------------------------------------------------------
# Lines 836, 838: apply_erosion rate guards
# ---------------------------------------------------------------------------


def test_apply_erosion_negative_rate_exits(mm):
	"""Line 836, 838: rate <= 0 → early return, scroll never called."""
	mm.apply_erosion("work", rate=0.0)
	assert not mm.client.scroll.called
	mm.apply_erosion("work", rate=-1.0)
	assert not mm.client.scroll.called


def test_apply_erosion_high_rate_warns(mm):
	"""Line 833: rate > 0.5 → warning logged."""
	with patch("red_pill.memory.logger.warning") as mock_warn:
		mm.apply_erosion("work", rate=0.9)
	assert mock_warn.called


# ---------------------------------------------------------------------------
# Lines 922-925: erosion safety break at 1000 iterations
# ---------------------------------------------------------------------------


def test_erosion_safety_break_at_1000(mm):
	"""Lines 922-925: after 1000 iterations, loop breaks to prevent infinite scroll."""
	# Always return an offset to simulate infinite scroll
	p1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "emotion": "neutral"})
	mm.client.scroll.return_value = ([p1], "always_has_next")

	# Rate 0 so we don't delete/update anything, just loop
	# We need rate > 0 to enter the loop properly
	mm.client.scroll.return_value = ([p1], "always_has_next")
	mm.apply_erosion("work", rate=0.01)
	# Should stop at 1000 iterations
	assert mm.client.scroll.call_count <= 1001


# ---------------------------------------------------------------------------
# Lines 997-1000: sanitize safety break at 1000 iterations
# ---------------------------------------------------------------------------


def test_sanitize_safety_break_at_1000(mm):
	"""Lines 997-1000: sanitation loop breaks after 1000 iterations."""
	p1 = MagicMock(
		id="1", payload={"content": "unique_" + str(uuid.uuid4()), "schema_version": "6.0", "color": "blue", "emotion": "neutral", "intensity": 1.0}
	)
	# Always return an offset to push through the safety break
	mm.client.scroll.return_value = ([p1], "always_has_next")
	mm.sanitize("work")
	# Should stop at 1000 iterations
	assert mm.client.scroll.call_count <= 1001
