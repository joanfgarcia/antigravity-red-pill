from unittest.mock import MagicMock

import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from red_pill.core.storage import StorageEngine


def test_storage_engine_retry_success():
	# Create a mock client
	mock_client = MagicMock()

	# Create storage engine with :memory: to avoid real network configuration
	engine = StorageEngine(url=":memory:")
	# Override client with mock
	engine.client = mock_client

	# Simulate 2 transient failures followed by success
	mock_client.retrieve.side_effect = [
		ResponseHandlingException(Exception("Connection reset by peer")),
		ResponseHandlingException(Exception("timeout")),
		[{"id": 1, "payload": {}}],
	]

	# Call retrieve
	result = engine.retrieve(collection_name="test_col", ids=[1])

	# Verify that we tried 3 times (2 failures + 1 success)
	assert mock_client.retrieve.call_count == 3
	assert result == [{"id": 1, "payload": {}}]


def test_storage_engine_retry_failure():
	# Create a mock client
	mock_client = MagicMock()

	# Create storage engine with :memory:
	engine = StorageEngine(url=":memory:")
	# Override client with mock
	engine.client = mock_client

	# Simulate 3 failures
	mock_client.retrieve.side_effect = [
		ResponseHandlingException(Exception("Connection reset by peer")),
		ResponseHandlingException(Exception("timeout")),
		ResponseHandlingException(Exception("disconnected")),
	]

	# Verify that calling retrieve raises the exception after 3 retries
	with pytest.raises(ResponseHandlingException):
		engine.retrieve(collection_name="test_col", ids=[1])

	# Verify that we tried exactly 3 times
	assert mock_client.retrieve.call_count == 3


def test_storage_engine_ensure_collection_retry():
	# Create a mock client
	mock_client = MagicMock()

	# Create storage engine with :memory:
	engine = StorageEngine(url=":memory:")
	# Override client with mock
	engine.client = mock_client

	# First attempt: collection_exists raises connection reset
	# Second attempt: collection_exists returns False, create_collection raises timeout
	# Third attempt: collection_exists returns True (already created or exists)
	mock_client.collection_exists.side_effect = [ResponseHandlingException(Exception("Connection reset by peer")), False, True]
	mock_client.create_collection.side_effect = [ResponseHandlingException(Exception("timeout"))]

	# Call ensure_collection
	engine.ensure_collection("test_col")

	# Verify collection_exists was called 3 times (attempt 1, attempt 2, attempt 3)
	assert mock_client.collection_exists.call_count == 3
	# create_collection was called 1 time (in attempt 2, before throwing)
	assert mock_client.create_collection.call_count == 1
