import pytest
import sys
import os
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

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

def test_immunity_promotion(manager, mock_qdrant):
    mock_hit = MagicMock()
    mock_hit.payload = {"reinforcement_score": 9.9, "content": "test"}
    mock_hit.id = "123"
    
    mock_response = MagicMock()
    mock_response.points = [mock_hit]
    manager.client.query_points.return_value = mock_response
    
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
    
    # Mock retrieval of association
    mock_assoc = MagicMock()
    mock_assoc.payload = {"reinforcement_score": 1.0, "content": "associated"}
    mock_assoc.id = "assoc_1"
    mock_assoc.vector = [0.2] * 384
    manager.client.retrieve.return_value = [mock_assoc]
    
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
    
    # Mock scroll result
    mock_hit = MagicMock()
    mock_hit.payload = {"reinforcement_score": 0.5, "immune": False}
    mock_hit.id = "123"
    mock_hit.vector = [0.1] * 384
    
    manager.client.scroll.side_effect = [
        ([mock_hit], "next"),
        ([], None)
    ]
    
    manager.apply_erosion("test_col")
    
    # Check upsert
    assert manager.client.upsert.called
    args, kwargs = manager.client.upsert.call_args
    assert kwargs['points'][0].payload['reinforcement_score'] == 0.4
