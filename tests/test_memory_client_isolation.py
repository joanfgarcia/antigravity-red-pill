import pytest

from red_pill.memory import MemoryManager


@pytest.fixture
def manager():
	return MemoryManager()
