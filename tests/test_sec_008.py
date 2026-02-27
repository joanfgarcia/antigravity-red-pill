from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as config
from red_pill.memory import MemoryManager


@pytest.fixture
def mock_qdrant():
	with patch("red_pill.memory.QdrantClient") as mock:
		yield mock


@pytest.fixture
def manager(mock_qdrant):
	mgr = MemoryManager()
	mgr._get_vector = MagicMock(return_value=[0.1] * config.VECTOR_SIZE)
	return mgr


def test_null_byte_rejection_metadata(manager):
	# Test null byte in metadata key
	with pytest.raises(ValueError, match="contains null bytes"):
		manager.add_memory("test", "content", metadata={"bad\x00key": "val"})

	# Test null byte in metadata value (string)
	with pytest.raises(ValueError, match="contains null bytes"):
		manager.add_memory("test", "content", metadata={"key": "bad\x00val"})

	# Test null byte in nested list
	with pytest.raises(ValueError, match="contains null bytes"):
		manager.add_memory("test", "content", metadata={"key": ["val1", "bad\x00val2"]})

	# Test null byte in metadata key (nested associations)
	# associations value is actually validated differently but general null byte check should catch it if it's a string
	with pytest.raises(ValueError, match="contains null bytes"):
		manager.add_memory("test", "content", metadata={"associations": ["bad\x00uuid"]})


def test_null_byte_rejection_content(manager):
	with pytest.raises(ValueError, match="Content contains null bytes"):
		manager.add_memory("test", "bad\x00content")
