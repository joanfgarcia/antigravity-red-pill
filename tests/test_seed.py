from unittest.mock import MagicMock

from red_pill.seed import seed_project


def test_seed_project_creates_collections():
    """Test that seed_project creates missing collections."""
    mock_manager = MagicMock()
    # Simulate collections do NOT exist
    mock_manager.client.collection_exists.return_value = False

    seed_project(mock_manager)

    # Assert collection creation was called twice (work, social)
    assert mock_manager.client.create_collection.call_count == 2

    args, kwargs = mock_manager.client.create_collection.call_args_list[0]
    assert kwargs['collection_name'] == "work_memories"

    args, kwargs = mock_manager.client.create_collection.call_args_list[1]
    assert kwargs['collection_name'] == "social_memories"

def test_seed_project_skips_if_genesis_present():
    """Test idempotency: seed_project skips seeding if Aleph's ID is found."""
    mock_manager = MagicMock()

    # Simulate collection exists and retrieve returns a hit
    mock_manager.client.collection_exists.return_value = True
    mock_manager.client.retrieve.return_value = [{"id": "00000000-0000-0000-0000-000000000001"}]

    seed_project(mock_manager)

    # Assert no memories were added
    mock_manager.add_memory.assert_not_called()

def test_seed_project_adds_memories():
    """Test that genesis memories are added if not present."""
    mock_manager = MagicMock()

    # Simulate collection exists but is empty (retrieve returns [])
    mock_manager.client.collection_exists.return_value = True
    mock_manager.client.retrieve.return_value = []

    seed_project(mock_manager)

    # Assert memory addition was called for each genesis item (currently 6 items)
    assert mock_manager.add_memory.call_count == 6

    # Check the first call parameters
    args, kwargs = mock_manager.add_memory.call_args_list[0]
    assert kwargs['point_id'] == "00000000-0000-0000-0000-000000000001"
    assert kwargs['metadata']['immune'] is True

def test_seed_project_exception_handled():
	"""Ensures exception during retrieve check is bypassed."""
	mock_manager = MagicMock()
	mock_manager.client.collection_exists.return_value = True
	mock_manager.client.retrieve.side_effect = Exception("DB Down")

	seed_project(mock_manager)

	# Should fall through and still attempt add_memory for genesis items
	assert mock_manager.add_memory.call_count == 6
