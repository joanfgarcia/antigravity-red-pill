import json
import sqlite3
import time
import uuid
from unittest.mock import MagicMock, patch

from red_pill.memory import MemoryManager
from red_pill.metabolism.sleep import perform_sleep_cycle
from red_pill.swarm.agents.janitor import JanitorMinion


@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
@patch("red_pill.metabolism.phases.consolidation.chunk_text", side_effect=lambda text: ["distilled compiler fix"] if "compiler error" in text else [])
def test_sleep_cycle_creates_parent_child_graph(mock_chunk, mock_llm):
	mock_mgr = MagicMock()
	mock_client = mock_mgr.client
	mock_client.collection_exists.return_value = True

	# Setup a mock interaction point in fast buffer
	raw_id = "test-raw-id"
	raw_point = MagicMock()
	raw_point.id = raw_id
	raw_point.payload = {"content": "USER: check compiler error\n\nASSISTANT: compile clean", "metadata": {"model": "opus", "category": "work"}}

	# Scroll calls: robust side effect function to handle multiple unexpected scrolls (like hub erosion or rhizodb wash)
	interaction_calls = 0

	def mock_scroll(collection_name, *args, **kwargs):
		nonlocal interaction_calls
		if collection_name == "interaction_memories":
			if interaction_calls == 0:
				interaction_calls += 1
				return ([raw_point], None)
			return ([], None)
		return ([], None)

	mock_client.scroll.side_effect = mock_scroll

	# Mock distill_engram to return 1 chunk
	with patch("red_pill.metabolism.phases.consolidation.distill_engram") as mock_distill:
		mock_distill.return_value = {"summary": "distilled compiler fix", "emotion": "neutral", "intensity": 0.8, "category": "work"}

		# Mock add_memory return values
		# First call in chunk loop, second for raw parent
		child_uuid = "child-uuid-123"
		parent_uuid = "00000000-0000-0000-0000-000000000456"
		mock_mgr.add_memory.side_effect = [child_uuid, parent_uuid]

		# Mock thread state loading/saving and uuid.uuid4
		with patch("red_pill.metabolism.phases.consolidation._load_thread_state", return_value={}):
			with patch("red_pill.metabolism.phases.consolidation._save_thread_state"):
				with patch("uuid.uuid4", return_value=uuid.UUID(parent_uuid)):
					processed = perform_sleep_cycle(mock_mgr)
					assert processed > 0

				# Verify sequence chunk added
				mock_mgr.add_memory.assert_any_call(
					collection="work_memories",
					text="distilled compiler fix",
					metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id, "model": "opus", "parent_id": parent_uuid},
					color="blue",
					emotion="neutral",
					intensity=0.8,
				)

				# Verify raw_parent engram added
				# The dynamic UUID generated in loop was passed to parent_id inside sequence_chunk metadata
				# Let's extract the actual parent_id passed to sequence_chunk
				calls = mock_mgr.add_memory.call_args_list
				passed_parent_id = calls[0][1]["metadata"]["parent_id"]

				mock_mgr.add_memory.assert_any_call(
					collection="work_memories",
					text="USER: check compiler error\n\nASSISTANT: compile clean",
					metadata={
						"lazarus_phase": "raw_parent",
						"source_buffer_id": raw_id,
						"model": "opus",
						"associations": [child_uuid],
						"immune": True,
					},
					point_id=passed_parent_id,
					force_immune=True,
				)

				# Verify raw buffer deleted
				mock_client.delete.assert_called_with(collection_name="interaction_memories", points_selector=[raw_id])


@patch("red_pill.metabolism.phases.consolidation.distill_session_anchors", return_value=None)
@patch("red_pill.metabolism.phases.consolidation._check_llm_available", return_value=True)
def test_sleep_cycle_dynamic_category_routing(mock_llm, mock_distill_anchors):
	"""Verify that chunks route dynamically based on their category."""
	mock_mgr = MagicMock()
	mock_client = mock_mgr.client
	mock_client.collection_exists.return_value = True

	raw_id = "test-raw-id-2"
	raw_point = MagicMock()
	raw_point.id = raw_id
	raw_point.payload = {
		"content": "USER: tell me a joke and write rust code\n\nASSISTANT: haha print",
		"metadata": {"model": "opus", "category": "mixed"},
	}

	interaction_calls = 0

	def mock_scroll(collection_name, *args, **kwargs):
		nonlocal interaction_calls
		if collection_name == "interaction_memories":
			if interaction_calls == 0:
				interaction_calls += 1
				return ([raw_point], None)
			return ([], None)
		return ([], None)

	mock_client.scroll.side_effect = mock_scroll

	with patch(
		"red_pill.metabolism.phases.consolidation.chunk_text", side_effect=lambda text: ["joke chunk", "code chunk"] if "joke and write rust" in text else []
	):
		with patch("red_pill.metabolism.phases.consolidation.synthesize_hub_v2", return_value={"title": "[Mixed Session]", "summary": "joke + code", "texture": "", "lang": ""}):
			with patch("red_pill.metabolism.phases.consolidation.distill_engram") as mock_distill:
				mock_distill.side_effect = [
					{"summary": "funny joke summary", "emotion": "joy", "intensity": 0.9, "category": "social"},
					{"summary": "rust code summary", "emotion": "neutral", "intensity": 0.8, "category": "work"},
				]

				child_id_1 = "child-joke-1"
				child_id_2 = "child-code-2"
				parent_id = "00000000-0000-0000-0000-000000000777"
				mock_mgr.add_memory.side_effect = [child_id_1, child_id_2, "hub-id-mixed", parent_id]

				with patch("red_pill.metabolism.phases.consolidation._load_thread_state", return_value={}):
					with patch("uuid.uuid4", return_value=uuid.UUID(parent_id)):
						processed = perform_sleep_cycle(mock_mgr)
						assert processed > 0

						# First chunk (joke) routed to social_memories
						mock_mgr.add_memory.assert_any_call(
							collection="social_memories",
							text="funny joke summary",
							metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id, "model": "opus", "parent_id": parent_id},
							color="purple",
							emotion="joy",
							intensity=0.9,
						)

						# Second chunk (code) routed to work_memories
						mock_mgr.add_memory.assert_any_call(
							collection="work_memories",
							text="rust code summary",
							metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id, "model": "opus", "parent_id": parent_id},
							color="blue",
							emotion="neutral",
							intensity=0.8,
						)


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

	purged = minion._cleanup_orphaned_parents(mock_mgr, "work_memories")
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

	purged = minion._cleanup_orphaned_parents(mock_mgr, "work_memories")
	assert purged == 0
	mock_client.delete.assert_not_called()


def test_janitor_archives_sqlite_to_jsonl(tmp_path):
	minion = JanitorMinion()

	# Setup temporary bunker.db
	db_dir = tmp_path / "storage" / "db"
	db_dir.mkdir(parents=True, exist_ok=True)
	db_file = db_dir / "bunker.db"

	conn = sqlite3.connect(str(db_file))
	conn.execute("""
		CREATE TABLE interactions (
			user_prompt TEXT,
			agent_response TEXT,
			timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			model TEXT
		)
	""")

	# Insert one row that is old (past 30 days cutoff) and one recent
	# SQLite format: YYYY-MM-DD HH:MM:SS
	old_ts = "2026-05-01 12:00:00"
	recent_ts = "2026-06-28 12:00:00"
	conn.execute("INSERT INTO interactions VALUES (?, ?, ?, ?)", ("old prompt", "old response", old_ts, "gpt4"))
	conn.execute("INSERT INTO interactions VALUES (?, ?, ?, ?)", ("recent prompt", "recent response", recent_ts, "opus"))
	conn.commit()
	conn.close()

	# Mock get_aleth_core_root() so the archived logs write to a temp folder
	aleth_core = tmp_path / "Aleth_Core"
	archive_file = aleth_core / "history" / "universal_history.jsonl"

	with patch("red_pill.core.paths.get_db_dir", return_value=db_dir):
		with patch("red_pill.core.paths.get_aleth_core_root", return_value=aleth_core):
			# Run archiver
			count = minion.archive_old_sqlite_interactions()
			assert count == 1

			# Verify JSONL log contains the old entry
			assert archive_file.exists()
			with open(archive_file) as f:
				lines = f.readlines()
				assert len(lines) == 1
				data = json.loads(lines[0])
				assert data["user_prompt"] == "old prompt"
				assert data["timestamp"] == old_ts
				assert data["model"] == "gpt4"

			# Verify SQLite database has only the recent row left
			conn2 = sqlite3.connect(str(db_file))
			cursor = conn2.cursor()
			cursor.execute("SELECT user_prompt FROM interactions")
			rows = cursor.fetchall()
			assert len(rows) == 1
			assert rows[0][0] == "recent prompt"
			conn2.close()
