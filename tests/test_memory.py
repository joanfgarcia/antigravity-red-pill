import pytest
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
    assert manager.client.upsert.called
    args, kwargs = manager.client.upsert.call_args
    points = kwargs['points']
    
    # Find points in list
    primary = next(p for p in points if p.id == "123")
    assoc = next(p for p in points if p.id == "assoc_1")
    
    assert primary.payload['reinforcement_score'] == 1.1
    assert primary.payload['reinforcement_score'] == 1.1
    assert assoc.payload['reinforcement_score'] == 1.05

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
    assert manager.client.upsert.called
    args, kwargs = manager.client.upsert.call_args
    points = kwargs['points']
    assert len(points) == 1
    assert points[0].id == "123"
    assert points[0].payload['reinforcement_score'] == 0.4

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
    args, kwargs = manager.client.upsert.call_args
    points = {p.id: p for p in kwargs['points']}
    
    assert points["A"].payload["reinforcement_score"] == 1.1
    assert points["B"].payload["reinforcement_score"] == 1.15
