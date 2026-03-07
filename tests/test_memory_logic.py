import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest

from red_pill.memory import MemoryManager, PointUpdate, _mask_pii_exception

# --- Fixtures ---


@pytest.fixture
def fake_cfg():
	cfg = SimpleNamespace()
	cfg.EMBEDDING_MODEL = "test_model"
	cfg.DECAY_STRATEGY = "exponential"
	cfg.DECAY_RATE = 0.01
	cfg.REINFORCEMENT_FACTOR = 1.1
	cfg.REINFORCEMENT_INCREMENT = 0.05
	cfg.MAX_AXONS = 5
	cfg.METABOLISM_STRATEGY = "LAZY"
	cfg.METABOLISM_ENABLED = True
	cfg.METABOLISM_COOLDOWN = 60
	cfg.ABSENCE_THRESHOLD = 86400
	cfg.ABSENCE_GUARD_SCROLL_LIMIT = 1000
	cfg.MAX_SINK_TIME = 2592000
	cfg.QDRANT_API_KEY = "test_key"
	cfg.QDRANT_URL = "http://localhost:6333"
	cfg.DEEP_RECALL_TRIGGERS = ["matrix", "oracle"]
	cfg.PROPAGATION_FACTOR = 0.5
	cfg.PROPAGATION_DEPTH = 2
	cfg.PROPAGATION_DECAY = 0.5
	cfg.MAX_PROPAGATION_POINTS = 100
	cfg.EROSION_RATE = 0.05
	cfg.IMMUNITY_THRESHOLD = 5.0
	cfg.EMOTIONAL_SEED_FACTOR = 0.2
	cfg.CURRENT_SCHEMA_VERSION = "6.0"
	cfg.METABOLISM_AUTO_COLLECTIONS = ["work_memories"]
	cfg.MULTI_EMOTION_INFERENCE = True
	cfg.DEFAULT_COLOR = "blue"
	cfg.DEFAULT_EMOTION = "neutral"
	cfg.CHUNK_THRESHOLD = 100
	cfg.DAEMON_SOCKET_PATH = "/tmp/red_pill_test.sock"
	cfg.SIDECAR_AUTH_KEY = "sidecar_secret"
	cfg.EXECUTION_PROVIDER = "cpu"
	cfg.METABOLISM_STATE_FILE = "/tmp/metabolism.json"
	cfg.EMOTIONAL_DECAY_MULTIPLIERS = {"blue": 1.0, "red": 2.0, "orange": 1.0, "joy": 0.8, "surprise": 1.0, "anger": 1.5, "neutral": 1.0}
	return cfg


@pytest.fixture
def mem_mgr(fake_cfg):
	with patch("fastembed.TextEmbedding") as MockTE:
		with patch("red_pill.memory.QdrantClient"):
			with patch("red_pill.memory.HiveMind"):
				mock_encoder = MagicMock()
				mock_encoder.embed.return_value = [[0.1] * 384]
				MockTE.return_value = mock_encoder
				mm = MemoryManager(config=fake_cfg)
				mm.encoder = mock_encoder
				mm.client.get_collection.return_value = MagicMock(config=MagicMock(params=MagicMock(vectors=MagicMock(size=384))))
				yield mm


# --- Unit Tests ---


def test_point_update_logic():
	p = PointUpdate("1", {"a": 1})
	assert p.id == "1"


def test_mask_pii_logic():
	assert "[TRUNCATED]" in _mask_pii_exception(Exception("x" * 500))


# --- Vector Helpers ---
def test_get_vector_error_handling(mem_mgr):
	mem_mgr.encoder.embed.return_value = []
	with pytest.raises(IndexError):
		mem_mgr._get_vector("test")


def test_get_vector_from_daemon_full_logic(mem_mgr):
	with patch("os.path.exists", return_value=True):
		with patch("socket.socket") as mock_sock:
			client = MagicMock()
			mock_sock.return_value.__enter__.return_value = client
			resp = json.dumps({"status": "ok", "vector": [0.4] * 384}).encode()
			client.recv.side_effect = [len(resp).to_bytes(4, "big"), resp]
			assert mem_mgr._get_vector_from_daemon("test") == [0.4] * 384
			client.recv.side_effect = [b""]
			assert mem_mgr._get_vector_from_daemon("test") is None


# --- add_memory branches ---
def test_add_memory_all_paths_final(mem_mgr, fake_cfg):
	with patch("red_pill.memory.record_interaction"):
		mem_mgr.add_memory("work", "text", color="orange", emotion="joy")
		fake_cfg.CHUNK_THRESHOLD = 2
		with patch("red_pill.memory.synaptic_split", return_value=["s1", "s2"]):
			mem_mgr.add_memory("work", "long")
		# Multi-emotion detection
		with patch("red_pill.memory.get_emotions", return_value=[{"label": "anger", "score": 1.0}]):
			with patch("red_pill.memory.get_chroma_for_emotion", return_value="red"):
				mem_mgr.add_memory("work", "anger detected")
		mem_mgr.add_memory("work", "immune", force_immune=True)


# --- update_memory branches ---
def test_update_memory_full_path(mem_mgr):
	mem_mgr.client.retrieve.return_value = [MagicMock(id="1")]
	assert mem_mgr.update_memory("work", "1", color="red", emotion="anger", intensity=5.0) is True
	mem_mgr.client.retrieve.return_value = []
	assert mem_mgr.update_memory("work", "unknown") is False
	assert mem_mgr.update_memory("work", None) is False


# --- Metabolism Branches ---
def test_metabolism_full_logic_final(mem_mgr, fake_cfg):
	mock_fcntl = MagicMock()
	with patch.dict("sys.modules", {"fcntl": mock_fcntl}):
		mock_fcntl.flock.side_effect = BlockingIOError
		with patch("builtins.open", mock_open()):
			with patch("os.path.exists", return_value=True):
				mem_mgr._run_metabolism_cycle()

		# 1. Switch to ACTIVE strategy to ensure apply_erosion is called
		mem_mgr.cfg.METABOLISM_STRATEGY = "ACTIVE"
		mem_mgr.cfg.METABOLISM_AUTO_COLLECTIONS = ["work_memories"]

		# 2. Setup a point with a COMPLETE payload to pass EngramPayload validation
		p1_payload = {
			"content": "test content",
			"importance": 1.0,
			"reinforcement_score": 5.0,
			"color": "blue",
			"emotion": "neutral",
			"intensity": 1.0,
			"immune": False,
			"created_at": time.time() - 20000,
			"last_recalled_at": time.time() - 10000,
			"schema_version": "6.0",
			"stability": 1.0,
			"difficulty": 5.0,
			"linguistic_markers": [],
		}
		p1 = MagicMock(id="1", payload=p1_payload)
		# Mock scroll to return the point
		mem_mgr.client.scroll.side_effect = [([p1], None), ([], None)]

		# 3. Patch internal state methods to bypass FileLock and open() complexity, and the new Sleep Engine
		with patch.object(mem_mgr, "_read_metabolism_state", return_value=(time.time() - 3601, False)):
			with patch.object(mem_mgr, "_write_metabolism_state"):
				with patch("os.path.exists", return_value=True):
					with patch("red_pill.metabolism.sleep.perform_sleep_cycle", return_value=0):
						mem_mgr._run_metabolism_cycle()

		# Check if either old set_payload or new batch_update_points was called
		assert mem_mgr.client.batch_update_points.called or mem_mgr.client.set_payload.called


# --- Reinforcement & Search ---
def test_reinforce_and_propagation_final(mem_mgr, fake_cfg):
	p1 = MagicMock(id=1, payload={"reinforcement_score": 0.5})
	mem_mgr.client.retrieve.return_value = [p1]
	res = mem_mgr._reinforce_points("work", [1], {"1": 0.1})
	assert len(res) == 1

	h1 = MagicMock(id="1", payload={"reinforcement_score": 0.5, "associations": ["2"]})
	mem_mgr.client.query_points.return_value = MagicMock(points=[h1])
	# depth 2 hop retrieval
	h2 = MagicMock(id="2", payload={"associations": [], "reinforcement_score": 0.5})
	mem_mgr.client.retrieve.return_value = [h2]

	mem_mgr.search_and_reinforce("work", "oracle query", deep_recall=True)
	assert mem_mgr.client.batch_update_points.called


# --- Maintenance ---
def test_erosion_purge_sanitize_final(mem_mgr):
	p1 = MagicMock(id="1", payload={"reinforcement_score": 0.01, "emotion": "neutral"})
	p2 = MagicMock(id="2", payload={"reinforcement_score": 1.0, "emotion": "joy", "intensity": 5.0})
	mem_mgr.client.scroll.side_effect = [([p1, p2], None)]
	mem_mgr.apply_erosion("work", rate=0.1)
	assert mem_mgr.client.delete.called

	p3 = MagicMock(id="3", payload={"content": "dupe", "schema_version": "1.0"})
	p4 = MagicMock(id="4", payload={"content": "dupe"})
	# p5 = MagicMock(id="5", payload={"content":"immune", "immune": True})
	mem_mgr.client.scroll.side_effect = [([p3, p4], None)]
	res = mem_mgr.sanitize("work")
	assert res["duplicates_found"] == 1

	mem_mgr.purge_dead_memories("work")
	assert mem_mgr.client.delete.called


def test_get_stats_final(mem_mgr):
	mem_mgr.client.get_collection.return_value = MagicMock(points_count=100)
	assert mem_mgr.get_stats("work")["points_count"] == 100


def test_calculate_lazy_decay_logic_final(mem_mgr, fake_cfg):
	payload = {"last_recalled_at": time.time() - 7200, "reinforcement_score": 0.5, "emotion": "joy", "intensity": 1.0}
	fake_cfg.METABOLISM_COOLDOWN = 3600
	fake_cfg.DECAY_STRATEGY = "exponential"
	score = mem_mgr._calculate_lazy_decay(payload)
	assert score < 0.5


# --- New tests to break 80% ---


def test_metabolism_no_fcntl(mem_mgr, fake_cfg):
	with patch.dict("sys.modules", {"fcntl": None}):
		with patch("builtins.open", mock_open(read_data="1700000000.0")):
			with patch("os.path.exists", return_value=True):
				mem_mgr._run_metabolism_cycle()


def test_reinforce_points_payload_none(mem_mgr):
	p1 = MagicMock(id="1", payload=None)
	mem_mgr.client.retrieve.return_value = [p1]
	assert mem_mgr._reinforce_points("work", ["1"], {"1": 0.1}) == []


def test_add_memory_exception_path(mem_mgr):
	with patch("red_pill.memory.record_interaction"):
		mem_mgr.client.upsert.side_effect = Exception("UPSERT FAIL")
		assert mem_mgr.add_memory("work", "fail") == ""


def test_search_and_reinforce_no_results(mem_mgr):
	mem_mgr.client.query_points.return_value = MagicMock(points=[])
	assert mem_mgr.search_and_reinforce("work", "query") == []


def test_apply_erosion_scroll_fail(mem_mgr):
	mem_mgr.client.scroll.side_effect = Exception("Scroll Fail")
	mem_mgr.apply_erosion("work")


def test_reinforce_points_batch_fail(mem_mgr):
	p1 = MagicMock(id="1", payload={"reinforcement_score": 0.5})
	mem_mgr.client.retrieve.return_value = [p1]
	mem_mgr.client.batch_update_points.side_effect = Exception("Batch Fail")
	assert mem_mgr._reinforce_points("work", ["1"], {"1": 0.1}) == []


def test_trigger_metabolism_called(mem_mgr):
	mem_mgr._trigger_metabolism()
	assert mem_mgr._metabolism_thread is not None
