import pytest
import uuid
from unittest.mock import MagicMock, patch
from red_pill.memory import MemoryManager
import red_pill.config as config

@pytest.fixture
def mock_qdrant():
    with patch('red_pill.memory.QdrantClient') as mock:
        yield mock

@pytest.fixture
def manager(mock_qdrant):
    return MemoryManager()

def test_linear_decay(manager):
    config.DECAY_STRATEGY = "linear"
    # 1.0 - 0.05 = 0.95
    assert manager._calculate_decay(1.0, 0.05) == 0.95
    # 0.04 - 0.05 = 0.0
    assert manager._calculate_decay(0.04, 0.05) == 0.0

def test_exponential_decay(manager):
    config.DECAY_STRATEGY = "exponential"
    # 1.0 * (1 - 0.05) = 0.95
    assert manager._calculate_decay(1.0, 0.05) == 0.95
    # 2.0 * (1 - 0.1) = 1.8
    assert manager._calculate_decay(2.0, 0.1) == 1.8

def test_exponential_decay_floor(manager):
    config.DECAY_STRATEGY = "exponential"
    # Test bug where 0.01 rounded to 2 decimal places stays 0.01
    # current=0.01, rate=0.05 -> 0.01 * 0.95 = 0.0095 -> round(0.01)
    # Our fix should force it down to 0.00
    assert manager._calculate_decay(0.01, 0.05) == 0.0

def test_immunity_promotion(manager, mock_qdrant):
    mock_hit = MagicMock()
    mock_hit.payload = {"reinforcement_score": 9.9, "content": "test"}
    mock_hit.id = "123"
    
    mock_response = MagicMock()
    mock_response.points = [mock_hit]
    manager.client.query_points.return_value = mock_response
    manager.client.retrieve.return_value = [mock_hit]
    
    results = manager.search_and_reinforce("test_col", "query")
    assert results[0].payload['reinforcement_score'] == 10.0
    assert results[0].payload['immune'] is True

def test_synaptic_propagation(manager, mock_qdrant):
    config.REINFORCEMENT_INCREMENT = 0.1
    config.PROPAGATION_FACTOR = 0.5
    
    # Mock search result with association
    mock_hit = MagicMock()
    mock_hit.payload = {"reinforcement_score": 1.0, "content": "primary", "associations": ["assoc_1"]}
    mock_hit.id = "123"
    mock_hit.vector = [0.1] * 384
    
    mock_response = MagicMock()
    mock_response.points = [mock_hit]
    manager.client.query_points.return_value = mock_response
    
    # Mock retrieval of BOTH primary and association
    mock_assoc = MagicMock()
    mock_assoc.payload = {"reinforcement_score": 1.0, "content": "associated"}
    mock_assoc.id = "assoc_1"
    mock_assoc.vector = [0.2] * 384
    manager.client.retrieve.return_value = [mock_hit, mock_assoc]
    
    manager.search_and_reinforce("test_col", "query")
    
    # Check upsert call
    # Check upsert call - we now use set_payload per point inside the loop
    # assert manager.client.upsert.called 
    # args, kwargs = manager.client.upsert.call_args
    # points = kwargs['points']
    
    assert manager.client.set_payload.called
    assert manager.client.set_payload.call_count == 2
    
    # Verify the calls
    calls = manager.client.set_payload.call_args_list
    
    # We don't know the order, so we collect payloads
    payloads = {}
    for call in calls:
        kwargs = call[1]
        pid = kwargs['points'][0]
        payload = kwargs['payload']
        payloads[pid] = payload
        
    assert "123" in payloads
    assert "assoc_1" in payloads
    
    assert payloads["123"]['reinforcement_score'] == 1.1
    assert payloads["assoc_1"]['reinforcement_score'] == 1.05

def test_erosion_cycle(manager, mock_qdrant):
    config.DECAY_STRATEGY = "linear"
    config.EROSION_RATE = 0.1
    
    # Mock scroll result: one normal, one immune
    mock_hit = MagicMock()
    mock_hit.payload = {"reinforcement_score": 0.5, "immune": False}
    mock_hit.id = "123"
    mock_hit.vector = [0.1] * 384
    
    mock_immune = MagicMock()
    mock_immune.payload = {"reinforcement_score": 10.0, "immune": True}
    mock_immune.id = "immune_1"
    
    manager.client.scroll.side_effect = [
        ([mock_hit, mock_immune], "next"),
        ([], None)
    ]
    
    manager.apply_erosion("test_col")
    
    # Check upsert was called with ONLY the non-immune point
    # Check upsert was called with ONLY the non-immune point
    # assert manager.client.upsert.called
    # args, kwargs = manager.client.upsert.call_args
    # points = kwargs['points']
    # assert len(points) == 1
    # assert points[0].id == "123"
    # assert points[0].payload['reinforcement_score'] == 0.4
    
    assert manager.client.set_payload.called
    assert manager.client.set_payload.call_count == 1
    
    args, kwargs = manager.client.set_payload.call_args
    assert kwargs['points'] == ["123"]
    assert kwargs['payload']['reinforcement_score'] == 0.4

def test_dormancy_filter(manager, mock_qdrant):
    mock_response = MagicMock()
    mock_response.points = []
    manager.client.query_points.return_value = mock_response
    
    # Normal search: should have filter
    manager.search_and_reinforce("test_col", "query", deep_recall=False)
    args, kwargs = manager.client.query_points.call_args
    assert kwargs['query_filter'] is not None
    # Check that filter has gte=0.2
    range_cond = kwargs['query_filter'].must[0].range
    assert range_cond.gte == 0.2
    
    # Deep Recall: filter should be None
    manager.search_and_reinforce("test_col", "query", deep_recall=True)
    args, kwargs = manager.client.query_points.call_args
    assert kwargs['query_filter'] is None

def test_reinforcement_stacking(manager, mock_qdrant):
    # Hit A associates with Hit B. Hit B is also a primary hit.
    # Base: 1.0. Hit A -> 1.1. Hit B -> 1.1 (primary) + 0.05 (assoc) = 1.15
    config.REINFORCEMENT_INCREMENT = 0.1
    config.PROPAGATION_FACTOR = 0.5
    
    hit_a = MagicMock(id="A", payload={"reinforcement_score": 1.0, "associations": ["B"]}, vector=[0.1]*384)
    hit_b = MagicMock(id="B", payload={"reinforcement_score": 1.0, "associations": []}, vector=[0.1]*384)
    
    mock_response = MagicMock()
    mock_response.points = [hit_a, hit_b]
    manager.client.query_points.return_value = mock_response
    manager.client.retrieve.return_value = [hit_a, hit_b]
    
    manager.search_and_reinforce("test_col", "query")
    
    # Check upsert
    # Check upsert
    # args, kwargs = manager.client.upsert.call_args
    # points = {p.id: p for p in kwargs['points']}
    # assert points["A"].payload["reinforcement_score"] == 1.1
    # assert points["B"].payload["reinforcement_score"] == 1.15
    
    assert manager.client.set_payload.called
    assert manager.client.set_payload.call_count == 2
    
    payloads = {}
    for call in manager.client.set_payload.call_args_list:
        kwargs = call[1]
        pid = kwargs['points'][0]
        payload = kwargs['payload']
        payloads[pid] = payload
        
    assert payloads["A"]['reinforcement_score'] == 1.1
    assert payloads["B"]['reinforcement_score'] == 1.15

def test_manual_id_injection(manager, mock_qdrant):
    # Test that add_memory respects a manual point_id
    manual_id = str(uuid.uuid4())
    returned_id = manager.add_memory("test_col", "content", point_id=manual_id)
    
    assert returned_id == manual_id
    args, kwargs = manager.client.upsert.call_args
    assert kwargs['points'][0].id == manual_id

def test_strict_id_validation(manager, mock_qdrant):
    # Test that _reinforce_points filters out garbage strings
    # We use a real increment map here
    increments = {"valid-uuid": 0.1, "garbage": 0.05}
    manager.client.retrieve.return_value = [] # Content doesn't matter, just the call
    
    manager._reinforce_points("test_col", ["valid-uuid", "garbage"], increments)
    
    # Check what was passed to retrieve
    args, kwargs = manager.client.retrieve.call_args
    # Since "garbage" is not a UUID, it should be filtered out
    # Wait, in our filter, we use uuid.UUID(str(pid))
    # "valid-uuid" would also fail if it's not a real UUID format.
    # Let's use real looking strings.
    real_uuid = str(uuid.uuid4())
    increments = {real_uuid: 0.1, "not-a-uuid": 0.05}
    
    manager._reinforce_points("test_col", [real_uuid, "not-a-uuid"], increments)
    args, kwargs = manager.client.retrieve.call_args
    assert real_uuid in kwargs['ids']
    assert "not-a-uuid" not in kwargs['ids']
