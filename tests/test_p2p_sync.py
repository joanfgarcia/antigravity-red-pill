import json
import os
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Generator

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.p2p_sync import (
	ChunkedPayloadTransmitter,
	SovereignSyncEngine,
	to_sqlite_timestamp,
)


@pytest.fixture
def temp_dbs() -> Generator[tuple[str, str], None, None]:
	"""Provides paths to two temporary SQLite databases."""
	fd1, path1 = tempfile.mkstemp(suffix="_db1.db")
	fd2, path2 = tempfile.mkstemp(suffix="_db2.db")
	os.close(fd1)
	os.close(fd2)

	yield path1, path2

	for path in (path1, path2):
		try:
			if os.path.exists(path):
				import gc
				gc.collect()
				os.remove(path)
		except PermissionError:
			pass


@pytest.fixture
def qdrant_clients() -> Generator[tuple[QdrantClient, QdrantClient], None, None]:
	"""Provides two isolated in-memory QdrantClient instances."""
	client1 = QdrantClient(location=":memory:")
	client2 = QdrantClient(location=":memory:")
	yield client1, client2
	client1.close()
	client2.close()


def test_sqlite_delta_lww_deduplication(temp_dbs):
	db1_path, db2_path = temp_dbs

	qm1 = CognitiveQueueManager(db_path=db1_path)
	CognitiveQueueManager(db_path=db2_path)

	task_id1 = qm1.enqueue_task(source="AgentSmith", payload={"action": "test1"}, priority=8)
	task_id2 = qm1.enqueue_task(source="Oracle", payload={"action": "test2"}, priority=5)

	now = time.time()
	source_ts1 = to_sqlite_timestamp(now + 10)
	source_ts2 = to_sqlite_timestamp(now - 10)

	with sqlite3.connect(db1_path) as conn:
		conn.execute("UPDATE cognitive_tasks SET updated_at = ? WHERE id = ?", (source_ts1, task_id1))
		conn.execute("UPDATE cognitive_tasks SET updated_at = ?, status = 'COMPLETED' WHERE id = ?", (source_ts2, task_id2))
		conn.commit()

	target_ts2 = to_sqlite_timestamp(now)
	with sqlite3.connect(db2_path) as conn:
		conn.execute(
			"""
			INSERT INTO cognitive_tasks (id, source, priority, payload, status, updated_at)
			VALUES (?, 'Oracle', 5, '{"action": "test2"}', 'PENDING', ?)
			""",
			(task_id2, target_ts2)
		)
		conn.commit()

	engine_src = SovereignSyncEngine(db_path=db1_path, qdrant_client=QdrantClient(location=":memory:"))
	engine_tgt = SovereignSyncEngine(db_path=db2_path, qdrant_client=QdrantClient(location=":memory:"))

	delta = engine_src.get_sqlite_delta(last_sync_timestamp=0)

	engine_tgt.apply_sqlite_delta(delta)

	with sqlite3.connect(db2_path) as conn:
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT status FROM cognitive_tasks WHERE id = ?", (task_id1,))
		row1 = cursor.fetchone()
		assert row1 is not None
		assert row1["status"] == "PENDING"

		cursor.execute("SELECT status FROM cognitive_tasks WHERE id = ?", (task_id2,))
		row2 = cursor.fetchone()
		assert row2 is not None
		assert row2["status"] == "PENDING"


def test_qdrant_point_delta_bidirectional_sync(qdrant_clients, temp_dbs):
	client_src, client_tgt = qdrant_clients
	db_src, db_tgt = temp_dbs

	coll_name = "work_memories"
	vector_size = 4

	client_src.create_collection(
		collection_name=coll_name,
		vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
	)
	client_tgt.create_collection(
		collection_name=coll_name,
		vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
	)

	now = time.time()

	p1_id = uuid.uuid4()
	p1_vector = [0.1, 0.2, 0.3, 0.4]
	p1_payload = {
		"content": "Source memory",
		"created_at": now + 5,
		"last_recalled_at": now + 5,
		"immune": False
	}

	p2_id = uuid.uuid4()
	p2_vector = [0.5, 0.6, 0.7, 0.8]
	p2_payload_src = {
		"content": "Shared memory updated on source",
		"created_at": now - 10,
		"last_recalled_at": now + 10,
		"reinforcement_score": 5.0
	}

	p3_id = uuid.uuid4()
	p3_vector = [0.9, 0.1, 0.2, 0.3]
	p3_payload_src = {
		"content": "Shared memory older on source",
		"created_at": now - 10,
		"last_recalled_at": now - 10,
		"reinforcement_score": 1.0
	}

	client_src.upsert(
		collection_name=coll_name,
		points=[
			models.PointStruct(id=p1_id, vector=p1_vector, payload=p1_payload),
			models.PointStruct(id=p2_id, vector=p2_vector, payload=p2_payload_src),
			models.PointStruct(id=p3_id, vector=p3_vector, payload=p3_payload_src)
		]
	)

	p2_payload_tgt = {
		"content": "Shared memory original target",
		"created_at": now - 10,
		"last_recalled_at": now,
		"reinforcement_score": 2.0
	}

	p3_payload_tgt = {
		"content": "Shared memory newer target",
		"created_at": now - 10,
		"last_recalled_at": now + 20,
		"reinforcement_score": 9.0
	}

	p4_id = uuid.uuid4()
	p4_vector = [0.2, 0.4, 0.6, 0.8]
	p4_payload = {
		"content": "Local target memory",
		"created_at": now,
		"last_recalled_at": now,
		"immune": True
	}

	client_tgt.upsert(
		collection_name=coll_name,
		points=[
			models.PointStruct(id=p2_id, vector=p2_vector, payload=p2_payload_tgt),
			models.PointStruct(id=p3_id, vector=p3_vector, payload=p3_payload_tgt),
			models.PointStruct(id=p4_id, vector=p4_vector, payload=p4_payload)
		]
	)

	engine_src = SovereignSyncEngine(db_path=db_src, qdrant_client=client_src)
	engine_tgt = SovereignSyncEngine(db_path=db_tgt, qdrant_client=client_tgt)

	qdrant_delta = engine_src.get_qdrant_delta(collections=[coll_name], last_sync_timestamp=now - 5)

	assert coll_name in qdrant_delta
	delta_points = qdrant_delta[coll_name]["points"]
	assert len(delta_points) == 2
	delta_ids = [dp["id"] for dp in delta_points]
	assert str(p1_id) in delta_ids
	assert str(p2_id) in delta_ids
	assert str(p3_id) not in delta_ids

	engine_tgt.apply_qdrant_delta(qdrant_delta)

	res = client_tgt.retrieve(collection_name=coll_name, ids=[p1_id, p2_id, p3_id, p4_id])
	res_map = {str(item.id): item for item in res}

	assert str(p1_id) in res_map
	assert res_map[str(p1_id)].payload["content"] == "Source memory"

	assert str(p2_id) in res_map
	assert res_map[str(p2_id)].payload["reinforcement_score"] == 5.0

	assert str(p3_id) in res_map
	assert res_map[str(p3_id)].payload["reinforcement_score"] == 9.0

	assert str(p4_id) in res_map
	assert res_map[str(p4_id)].payload["content"] == "Local target memory"


def test_chunking_integrity_and_reassembly():
	transmitter = ChunkedPayloadTransmitter(chunk_size=10)

	original_data = b"This is a relatively long test payload that we will split into multiple smaller chunks to assert reassembly integrity, SHA-256 validation, and packet-loss validation."

	chunks = transmitter.chunk_payload(original_data)
	assert len(chunks) > 1
	assert chunks[0]["total_chunks"] == len(chunks)

	assembled = None
	for c in chunks:
		assembled = transmitter.receive_chunk(c)

	assert assembled == original_data

	chunks = transmitter.chunk_payload(original_data)
	corrupt_chunk = chunks[0].copy()
	corrupt_chunk["payload"] = corrupt_chunk["payload"] + "corrupt"

	with pytest.raises(ValueError, match="Corrupt chunk checksum mismatch"):
		transmitter.receive_chunk(corrupt_chunk)

	chunks = transmitter.chunk_payload(original_data)
	assembled = None
	for c in chunks[:-1]:
		assembled = transmitter.receive_chunk(c)
	assert assembled is None


def test_transmission_and_incoming_processing(qdrant_clients, temp_dbs, monkeypatch):
	client_src, client_tgt = qdrant_clients
	db_src, db_tgt = temp_dbs

	fd_nl, path_nl = tempfile.mkstemp(suffix="_neon_link.db")
	os.close(fd_nl)

	with sqlite3.connect(path_nl) as conn:
		conn.execute("""
			CREATE TABLE IF NOT EXISTS outbox (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				channel TEXT,
				channel_user_id TEXT,
				payload TEXT,
				status TEXT DEFAULT 'PENDING'
			)
		""")
		conn.commit()

	import red_pill.core.paths as paths
	monkeypatch.setattr(paths, "get_neon_link_db_path", lambda: Path(path_nl))

	engine_src = SovereignSyncEngine(db_path=db_src, qdrant_client=client_src)
	engine_tgt = SovereignSyncEngine(db_path=db_tgt, qdrant_client=client_tgt)

	coll_name = "work_memories"
	client_src.create_collection(
		collection_name=coll_name,
		vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE)
	)

	client_src.upsert(
		collection_name=coll_name,
		points=[
			models.PointStruct(
				id=uuid.uuid4(),
				vector=[0.1, 0.2, 0.3, 0.4],
				payload={"content": "Sync me!", "created_at": time.time(), "last_recalled_at": time.time()}
			)
		]
	)

	engine_src.transmit_sync_payload(
		target_peer="TargetPeer",
		collections=[coll_name],
		last_sync_timestamp=0
	)

	with sqlite3.connect(path_nl) as conn:
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()
		cursor.execute("SELECT * FROM outbox")
		rows = cursor.fetchall()
		assert len(rows) > 0
		assert rows[0]["channel"] == "rings"
		assert rows[0]["channel_user_id"] == "TargetPeer"

		from red_pill.core.inbox import MinionInbox
		inbox_tgt = MinionInbox()
		for r in rows:
			payload_data = json.loads(r["payload"])
			inbox_tgt.drop_report(
				event_id=f"test_sync_{uuid.uuid4()}",
				source="NeonLink (rings)",
				status="pending",
				content=payload_data["text"]
			)

	applied = engine_tgt.process_incoming_syncs()
	assert applied == 1

	assert client_tgt.collection_exists(coll_name)
	res, _ = client_tgt.scroll(collection_name=coll_name, limit=1)
	assert len(res) == 1
	assert res[0].payload["content"] == "Sync me!"

	try:
		if os.path.exists(path_nl):
			os.remove(path_nl)
	except PermissionError:
		pass
