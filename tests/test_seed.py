import pytest
from unittest.mock import MagicMock
from red_pill.seed import seed_project

@pytest.fixture
def mock_manager():
	return MagicMock()

def test_seed_project_creates_collections(mock_manager):
	"""Test that seed_project creates missing collections."""
	# Simulate collections do NOT exist
	mock_manager.client.collection_exists.return_value = False

	seed_project(mock_manager)

	# Assert collection creation was called thrice (work, social, directive)
	assert mock_manager.client.create_collection.call_count == 3

	args, kwargs = mock_manager.client.create_collection.call_args_list[0]
	assert kwargs["collection_name"] == "work_memories"

	args, kwargs = mock_manager.client.create_collection.call_args_list[1]
	assert kwargs["collection_name"] == "social_memories"

	args, kwargs = mock_manager.client.create_collection.call_args_list[2]
	assert kwargs["collection_name"] == "directive_memories"

def test_seed_project_adds_memories(mock_manager):
	"""Test that genesis memories are added if not present."""
	# Mock retrieve to return empty list (memories don't exist yet)
	mock_manager.client.retrieve.return_value = []

	seed_project(mock_manager)

	# 6 original + 3 directives
	assert mock_manager.add_memory.call_count == 9

	# Check the first call parameters
	args, kwargs = mock_manager.add_memory.call_args_list[0]
	assert kwargs["point_id"] == "00000000-0000-0000-0000-000000000001"
	assert kwargs["metadata"]["immune"] is True

def test_seed_project_exception_handled(mock_manager):
	"""Ensures exception during retrieve check is bypassed."""
	mock_manager.client.collection_exists.return_value = True
	mock_manager.client.retrieve.side_effect = Exception("DB Down")

	seed_project(mock_manager)

	# Should fall through and still attempt add_memory for all 9 genesis items
	assert mock_manager.add_memory.call_count == 9

def test_seed_project_skips_if_present(mock_manager):
	"""Test idempotency: seed_project skips seeding if IDs are found."""
	# Mock retrieve to return a hit
	mock_manager.client.retrieve.return_value = [{"id": "some-id"}]

	seed_project(mock_manager)

	assert mock_manager.add_memory.call_count == 0
