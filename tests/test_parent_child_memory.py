import time
from unittest.mock import MagicMock, patch

from red_pill.memory import MemoryManager
from red_pill.swarm.agents.janitor import JanitorMinion
from red_pill.swarm.agents.janitor_plugins.orphaned_parents_sweep import OrphanedParentsSweepPlugin


def test_search_excludes_raw_parents_by_default():
	mock_client = MagicMock()

	# Mock results
	now = time.time()
	payload_base = {
		"importance": 5.0,
		"created_at": now,
		"last_recalled_at": now,
		"schema_version": 1,
		"utility_alpha": 10.0,
		"utility_beta": 1.0,
	}
	hit_concept = MagicMock(id="1", payload={**payload_base, "content": "semantic concept", "lazarus_phase": "sequence_chunk"})
	_hit_parent = MagicMock(id="2", payload={**payload_base, "content": "raw verbatim chat", "lazarus_phase": "raw_parent"})

	# Under normal conditions, query_points is called. We verify the query_filter has must_not conditions.
	with patch("red_pill.core.storage.QdrantClient", return_value=mock_client):
		mgr = MemoryManager(url=":memory:")
		mgr.client = mock_client

		# Mock Qdrant results returning only the concept
		mock_query_res = MagicMock()
		mock_query_res.points = [hit_concept]
		mock_client.query_points.return_value = mock_query_res

		results = mgr.search_and_reinforce("work_memories", "query text")
		assert len(results) == 1
		assert results[0].payload["lazarus_phase"] == "sequence_chunk"

		# Verify that query_filter has the must_not condition for raw_parent
		call_args = mock_client.query_points.call_args[1]
		query_filter = call_args["query_filter"]
		assert query_filter is not None

		# must_not condition check
		must_not = query_filter.must_not
		assert len(must_not) > 0
		assert must_not[0].key == "lazarus_phase"
		assert must_not[0].match.value == "raw_parent"


def test_retrieve_parent_context():
	mock_client = MagicMock()
	child_id = "child-id-1"
	parent_id = "parent-id-2"

	child_point = MagicMock(id=child_id, payload={"content": "concept", "parent_id": parent_id})
	parent_point = MagicMock(
		id=parent_id,
		payload={
			"content": "raw transcript",
			"importance": 5.0,
			"reinforcement_score": 10.0,
			"created_at": time.time(),
			"last_recalled_at": time.time(),
			"immune": True,
			"color": "gray",
			"emotion": "neutral",
			"intensity": 1.0,
			"schema_version": 1,
			"lazarus_phase": "raw_parent",
		},
	)

	with patch("red_pill.core.storage.QdrantClient", return_value=mock_client):
		mgr = MemoryManager(url=":memory:")
		mgr.client = mock_client

		# Mock retrieve to return child from work_memories, then parent from work_memories
		mock_client.retrieve.side_effect = [[child_point], [parent_point]]

		parent_ctx = mgr.retrieve_parent_context(child_id)
		assert parent_ctx is not None
		assert parent_ctx["lazarus_phase"] == "raw_parent"
		assert parent_ctx["content"] == "raw transcript"


def test_janitor_cleans_orphaned_parents():
	minion = JanitorMinion()
	mock_mgr = MagicMock()
	mock_client = mock_mgr.client
	mock_client.collection_exists.return_value = True

	parent_id = "parent-uuid"
	parent_point = MagicMock(id=parent_id, payload={"lazarus_phase": "raw_parent", "associations": ["child-id-1"]})

	# Scroll retrieves parent, next returns empty
	mock_client.scroll.side_effect = [([parent_point], None), ([], None)]

	# child retrieve returns empty list (meaning child was deleted!)
	mock_client.retrieve.return_value = []

	purged = OrphanedParentsSweepPlugin()._cleanup_orphaned_parents(minion, mock_mgr, "work_memories")
	assert purged == 1
	mock_client.delete.assert_called_once()


def test_janitor_does_not_clean_parents_with_live_children():
	minion = JanitorMinion()
	mock_mgr = MagicMock()
	mock_client = mock_mgr.client
	mock_client.collection_exists.return_value = True

	parent_id = "parent-uuid"
	child_id = "child-id-1"
	parent_point = MagicMock(id=parent_id, payload={"lazarus_phase": "raw_parent", "associations": [child_id]})

	mock_client.scroll.side_effect = [([parent_point], None), ([], None)]

	# child retrieve returns the live child engram
	child_point = MagicMock(id=child_id, payload={"lazarus_phase": "sequence_chunk"})
	mock_client.retrieve.return_value = [child_point]

	purged = OrphanedParentsSweepPlugin()._cleanup_orphaned_parents(minion, mock_mgr, "work_memories")
	assert purged == 0
	mock_client.delete.assert_not_called()
