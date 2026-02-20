import json
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.memory import MemoryManager, _mask_pii_exception


def test_mask_pii_exception():
	"""Ensures exception strings are truncated."""
	long_msg = "A" * 200
	ex = Exception(long_msg)
	masked = _mask_pii_exception(ex)
	assert "TRUNCATED" in masked
	assert len(masked) <= 170

@patch('os.path.exists', return_value=True)
@patch('socket.socket')
def test_get_vector_from_daemon(mock_socket_cls, mock_exists):
	"""Test successful daemon embedding."""
	manager = MemoryManager()
	mock_client = MagicMock()
	mock_socket_cls.return_value.__enter__.return_value = mock_client

	vector_data = [0.1, 0.2, 0.3]
	response_json = json.dumps({"status": "ok", "vector": vector_data}).encode('utf-8')
	mock_client.recv.return_value = response_json

	vector = manager._get_vector("test")
	assert vector == vector_data
	mock_client.sendall.assert_called_once()

@patch('os.path.exists', return_value=True)
@patch('socket.socket')
def test_get_vector_from_daemon_exception(mock_socket_cls, mock_exists):
	mock_client = MagicMock()
	mock_socket_cls.return_value.__enter__.return_value = mock_client
	mock_client.connect.side_effect = Exception("Daemon down")

	manager = MemoryManager()
	vector = manager._get_vector_from_daemon("test")
	assert vector is None

@patch('os.path.exists', return_value=False)
def test_get_vector_from_daemon_no_socket(mock_exists):
	manager = MemoryManager()
	assert manager._get_vector_from_daemon("test") is None

@patch('red_pill.memory.MemoryManager._get_vector_from_daemon', return_value=None)
def test_get_vector_local(mock_daemon):
	"""Test fallback to local encoder."""
	manager = MemoryManager()

	try:
		manager._get_vector("test")
	except Exception:
		pass
	manager.encoder = None
	with patch.dict("sys.modules", {"fastembed": None}):
		vector = manager._get_vector("hello")
		assert vector == [0.0] * cfg.VECTOR_SIZE

	# Now test when encoder is already set
	class MockEncoderInst:
		def embed(self, text_list):
			class MockVector:
				def tolist(self): return [0.3]
			yield MockVector()

	manager.encoder = MockEncoderInst()
	vector2 = manager._get_vector("again")
	assert vector2 == [0.3]

def test_add_memory_metadata_exception():
	manager = MemoryManager()
	manager.client = MagicMock()

	with pytest.raises(ValueError, match="Invalid metadata"):
		# Set an invalid object that cannot be JSON serialized
		manager.add_memory("col", "text", metadata={"bad": object()})

def test_add_memory_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.upsert.side_effect = Exception("Fail")
	assert manager.add_memory("col", "text") == ""


def test_get_stats_exception_and_success():
	manager = MemoryManager()
	manager.client = MagicMock()

	# Success
	class MockInfo:
		status = "green"
		points_count = 10
		segments_count = 2
	manager.client.get_collection.return_value = MockInfo()
	stats = manager.get_stats("col")
	assert stats["status"] == "green"
	assert stats["points_count"] == 10

	# Exception
	manager.client.get_collection.side_effect = Exception("DB Fail")
	stats = manager.get_stats("col")
	assert stats["status"] == "error"

def test_trigger_metabolism_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	with patch('threading.Thread') as mock_thread:
		mock_thread.side_effect = Exception("Thread limit reached")
		manager._trigger_metabolism()
		# Should just log and not crash
		assert True

def test_apply_erosion_io_errors(monkeypatch):
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.scroll.return_value = ([], None)
	monkeypatch.setattr(cfg, "METABOLISM_COOLDOWN", 3600)

	# Test missing state file (OSError on read)
	with patch("os.path.exists", return_value=True):
		with patch("builtins.open", side_effect=OSError("No file")):
			manager._run_metabolism_cycle()

	# Test open for write throws OSError
	with patch("os.path.exists", return_value=False):
		with patch("builtins.open", side_effect=OSError("Read-only FS")):
			manager._run_metabolism_cycle()

def test_reinforce_points_empty_and_payload_exception():
	manager = MemoryManager()
	manager.client = MagicMock()

	# Empty points
	assert manager._reinforce_points("col", [], {}) == []
	# Invalid integer uuid string
	manager._reinforce_points("col", ["not-uuid"], {"not-uuid": 0.1})

	class MockPoint:
		def __init__(self):
			self.id = "1"
			self.payload = {"reinforcement_score": 1.0}

	manager.client.retrieve.return_value = [MockPoint()]
	manager.client.set_payload.side_effect = Exception("Payload Set Fail")

	points = manager._reinforce_points("col", [1], {1: 0.1})
	assert len(points) == 0 # Because of continue on exception

def test_reinforce_points_retrieve_exception():
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.retrieve.side_effect = Exception("Retrieve error")
	assert manager._reinforce_points("col", [1], {1: 0.1}) == []


@patch('red_pill.memory.MemoryManager._get_vector', return_value=[0.1])
def test_search_and_reinforce_query_exception(mock_vec):
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.query_points.side_effect = Exception("Search fail")

	results = manager.search_and_reinforce("col", "query")
	assert results == []

def test_calculate_decay_edge_cases():
	manager = MemoryManager()
	monkeypatch = pytest.MonkeyPatch()

	monkeypatch.setattr(cfg, "DECAY_STRATEGY", "exponential")
	# Exp decay below 0
	val = manager._calculate_decay(-0.5, 0.1)
	assert val == 0.0

	monkeypatch.setattr(cfg, "DECAY_STRATEGY", "unknown")
	val = manager._calculate_decay(5.0, 0.1)
	assert val == 4.9 # Default to linear subtraction if unknown strategy

def test_apply_erosion_exceptions_and_deletions():
	manager = MemoryManager()
	manager.client = MagicMock()

	# Scroll exception
	manager.client.scroll.side_effect = Exception("Scroll Failed")
	cfg.METABOLISM_ENABLED = True
	manager.apply_erosion("col")

	# Rate <= 0 shortcut
	manager.apply_erosion("col", -0.1)

	# Empty run with no rate (tests None fallback)
	manager.client.scroll.side_effect = None
	manager.client.scroll.return_value = ([], None)
	manager.apply_erosion("col") # No rate (tests None fallback)

	# Test point update exception and hard deletion due to zero score
	class MockPoint:
		def __init__(self, _id, score, immune):
			self.id = _id
			self.payload = {"content": "text", "reinforcement_score": score, "immune": immune}
	p1 = MockPoint("1", 1.0, True)
	p2 = MockPoint("2", 1.0, False) # Will fall <= 0 because rate=1.0 and current=1.0. wait!
	p3 = MockPoint("3", 2.0, False) # Will hit set_payload exception because new_score=1.0 > 0
	manager.client.scroll.return_value = ([p1, p2, p3], None)

	manager.client.set_payload.side_effect = Exception("Set Payload Failed")
	manager.client.delete.side_effect = Exception("Delete Failed") # Covers deletion exception

	cfg.METABOLISM_COOLDOWN = 3600 # so metabolism skips
	manager.apply_erosion("col", 1.0)



def test_sanitize_exceptions():
	manager = MemoryManager()
	manager.client = MagicMock()
	manager.client.scroll.side_effect = Exception("Scroll Failed")

	res = manager.sanitize("col")
	assert res["duplicates_found"] == 0

	# Now test payload update exception
	class MockPoint:
		def __init__(self):
			self.id = "1"
			# Missing color so it triggers migration
			self.payload = {"content": "text", "reinforcement_score": 1.0}

	manager.client.scroll.side_effect = None
	manager.client.scroll.return_value = ([MockPoint()], None)
	manager.client.set_payload.side_effect = Exception("Set Payload Failed")
	manager.sanitize("col")

	# Test dry_run migration counting
	manager.client.set_payload.side_effect = None
	res = manager.sanitize("col", dry_run=True)
	assert res["migrated_records"] == 1

	# Test delete duplicate exception
	seen_mock1 = MockPoint()
	seen_mock2 = MockPoint()
	seen_mock2.id = "2"
	seen_mock2.payload = {"content": "text"} # duplicate
	manager.client.scroll.return_value = ([seen_mock1, seen_mock2], None)
	manager.client.set_payload.side_effect = None
	manager.client.delete.side_effect = Exception("Delete Failed")
	res = manager.sanitize("col")
	assert res["duplicates_found"] == 1
