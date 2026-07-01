import logging
import time
import uuid
from typing import Any, Dict, List

from qdrant_client import QdrantClient
from qdrant_client.http import models

import red_pill.config as cfg
from red_pill.core.embeddings import EmbeddingEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sandbox_memory_graph")


def run_sandbox():
	print("\n=== STARTING SANDBOX MEMORY GRAPH SIMULATION ===\n")

	# 1. Initialize client & engines
	client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
	embedding_engine = EmbeddingEngine()

	test_work_col = "sandbox_work_memories"
	test_social_col = "sandbox_social_memories"

	# 2. Cleanup old test collections if any
	for col in [test_work_col, test_social_col]:
		if client.collection_exists(col):
			client.delete_collection(col)
		client.create_collection(collection_name=col, vectors_config=models.VectorParams(size=cfg.VECTOR_SIZE, distance=models.Distance.COSINE))
		print(f"[Sandbox] Initialized clean test collection: {col}")

	# 3. Retrieve representative sample of 100 engrams from work_memories
	source_col = "work_memories"
	if not client.collection_exists(source_col):
		print(f"[Error] Source collection '{source_col}' does not exist! Aborting sandbox.")
		return

	print(f"[Sandbox] Scrolling up to 100 engrams from {source_col}...")
	records, _ = client.scroll(collection_name=source_col, limit=100, with_payload=True, with_vectors=True)

	if not records:
		print("[Warning] No engrams found in live work_memories. Seeding test points instead...")
		# Seed some test points
		test_records = []
		for i in range(20):
			uid = str(uuid.uuid4())
			content = f"Seed test engram {i} for workspace debugging."
			vector = embedding_engine.get_vector(content)
			# Group into 4 synthetic sessions
			session_id = f"sess_seed_{i // 5}"
			payload = {
				"content": content,
				"importance": 5.0,
				"reinforcement_score": 1.0,
				"created_at": time.time(),
				"last_recalled_at": time.time(),
				"immune": False,
				"color": "blue",
				"emotion": "neutral",
				"intensity": 1.0,
				"schema_version": cfg.CURRENT_SCHEMA_VERSION,
				"source_buffer_id": session_id,
				"lazarus_phase": "sequence_chunk",
			}
			test_records.append(models.Record(id=uid, payload=payload, vector=vector))
		records = test_records
	else:
		print(f"[Sandbox] Successfully loaded {len(records)} engrams from live work_memories.")

	# 4. Group by source_buffer_id
	grouped_engrams: Dict[str, List[Any]] = {}
	for r in records:
		payload = r.payload or {}
		sb_id = payload.get("source_buffer_id") or payload.get("metadata", {}).get("source_buffer_id")
		if sb_id:
			sb_id_str = str(sb_id)
			if sb_id_str not in grouped_engrams:
				grouped_engrams[sb_id_str] = []
			grouped_engrams[sb_id_str].append(r)

	print(f"[Sandbox] Found {len(grouped_engrams)} groups of engrams aligned by source_buffer_id.")

	# 5. Benchmark parent synthesis, vector embedding, and uploads
	start_time = time.time()
	processed_count = 0
	parent_ids = []

	# Parent Threading state tracking (simulated)
	last_parent_id = None

	for sb_id, child_nodes in grouped_engrams.items():
		print(f"\n[Sandbox] Processing group: {sb_id} with {len(child_nodes)} chunks...")

		# Generate a parent UUID
		parent_uuid = str(uuid.uuid4())

		# Synthesize parent text by concatenating summaries or content snippets
		synthesized_text = ""
		child_ids = []
		for i, child in enumerate(child_nodes):
			child_ids.append(str(child.id))
			content = child.payload.get("content", "")
			synthesized_text += f"Chunk {i + 1}: {content}\n\n"

		# Embed the parent text
		parent_vector = embedding_engine.get_vector(synthesized_text)

		# Write Parent Engram (Simulating work_memories placement)
		parent_payload = {
			"content": synthesized_text,
			"importance": 5.0,
			"reinforcement_score": 10.0,  # Immune baseline
			"created_at": time.time(),
			"last_recalled_at": time.time(),
			"immune": True,
			"color": "gray",
			"emotion": "neutral",
			"intensity": 1.0,
			"schema_version": cfg.CURRENT_SCHEMA_VERSION,
			"lazarus_phase": "raw_parent",
			"source_buffer_id": sb_id,
			"associations": child_ids,
		}

		# Apply Ariadne parent threading
		if last_parent_id:
			parent_payload["prev_raw_parent"] = last_parent_id

		client.upsert(collection_name=test_work_col, points=[models.PointStruct(id=parent_uuid, payload=parent_payload, vector=parent_vector)])

		# Thread update forward connection (simulated)
		if last_parent_id:
			client.set_payload(collection_name=test_work_col, payload={"next_raw_parent": parent_uuid}, points=[last_parent_id])

		last_parent_id = parent_uuid
		parent_ids.append(parent_uuid)

		# Write child engrams with parent_id link (cloned vectors)
		for child in child_nodes:
			child_payload = dict(child.payload) if child.payload else {}
			child_payload["parent_id"] = parent_uuid
			child_payload["lazarus_phase"] = "sequence_chunk"

			# Dynamic category routing simulation (alternating work/social for test)
			target_col = test_work_col if processed_count % 2 == 0 else test_social_col

			client.upsert(collection_name=target_col, points=[models.PointStruct(id=child.id, payload=child_payload, vector=child.vector)])
			processed_count += 1

	elapsed_time = time.time() - start_time
	avg_time_per_group = elapsed_time / max(1, len(grouped_engrams))
	avg_time_per_engram = elapsed_time / max(1, processed_count)

	# Extrapolate for 8,270 engrams
	est_total_seconds = avg_time_per_engram * 8270

	print("\n" + "=" * 50)
	print("BENCHMARK REPORT")
	print("=" * 50)
	print(f"Total groups processed:     {len(grouped_engrams)}")
	print(f"Total child nodes processed: {processed_count}")
	print(f"Total elapsed time:         {elapsed_time:.4f} seconds")
	print(f"Avg time per group:         {avg_time_per_group * 1000:.2f} ms")
	print(f"Avg time per engram:        {avg_time_per_engram * 1000:.2f} ms")
	print(f"Estimated Prod Migration:   {est_total_seconds:.2f} seconds (for 8,270 engrams)")
	print("=" * 50 + "\n")

	# 6. Verify Isolation & Query Logic
	print("--- VERIFICATION QUERIES ---")

	# Query 1: Default Search (should filter out raw_parents)
	test_query_content = "workspace debugging"
	query_vector = embedding_engine.get_vector(test_query_content)

	must_not_conditions = [models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent"))]

	# Query Qdrant with filter (simulating memory.py filter)
	search_filter = models.Filter(must_not=must_not_conditions)

	results = client.query_points(collection_name=test_work_col, query=query_vector, query_filter=search_filter, limit=5, with_payload=True).points

	print("\n[Query 1] Default Search (Filters raw_parent):")
	raw_parent_returned = False
	for hit in results:
		l_phase = hit.payload.get("lazarus_phase")
		print(f" - Hit ID: {hit.id} | lazarus_phase: {l_phase} | Score: {hit.score:.4f} | Snippet: {hit.payload.get('content')[:50]}")
		if l_phase == "raw_parent":
			raw_parent_returned = True

	if raw_parent_returned:
		print("❌ FAILURE: General search returned a raw_parent engram!")
	else:
		print("✅ SUCCESS: General search successfully isolated raw_parent engrams.")

	# Query 2: Retrieve Parent Context
	print("\n[Query 2] Verifying Parent Context Traversal:")
	child_results = client.query_points(
		collection_name=test_work_col,
		query=query_vector,
		query_filter=models.Filter(must=[models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="sequence_chunk"))]),
		limit=1,
		with_payload=True,
	).points

	if child_results:
		child_hit = child_results[0]
		child_id = child_hit.id
		parent_uuid_linked = child_hit.payload.get("parent_id")
		print(f" - Found child engram: {child_id} linking to parent_id: {parent_uuid_linked}")

		# Retrieve parent engram from test_work_col
		parent_points = client.retrieve(collection_name=test_work_col, ids=[parent_uuid_linked], with_payload=True)

		if parent_points and parent_points[0].payload:
			parent_payload = parent_points[0].payload
			print(" - Successfully retrieved parent verbatim engram!")
			print(f" - Parent associations count: {len(parent_payload.get('associations', []))}")
			print(f" - Parent snippet: {parent_payload.get('content')[:120]}...")
			print("✅ SUCCESS: Parent context traversal works.")
		else:
			print("❌ FAILURE: Could not retrieve parent engram by parent_id link.")
	else:
		print("[Sandbox] No child nodes matched query for parent traversal test.")

	# Query 3: Ariadne Parent-to-Parent Thread Walking
	print("\n[Query 3] Verifying Ariadne's Thread Walking (temporal chaining):")
	if len(parent_ids) >= 2:
		first_parent_id = parent_ids[0]
		first_parent = client.retrieve(collection_name=test_work_col, ids=[first_parent_id], with_payload=True)[0]
		next_id = first_parent.payload.get("next_raw_parent")
		print(f" - First Parent ID: {first_parent_id}")
		print(f" - Next Parent link: {next_id}")

		if next_id:
			second_parent = client.retrieve(collection_name=test_work_col, ids=[next_id], with_payload=True)[0]
			prev_id = second_parent.payload.get("prev_raw_parent")
			print(f" - Second Parent ID: {next_id}")
			print(f" - Prev Parent link: {prev_id}")
			if prev_id == first_parent_id:
				print("✅ SUCCESS: Ariadne's parent thread walked backwards and forwards correctly.")
			else:
				print("❌ FAILURE: Ariadne parent-to-parent thread back-link is broken.")
		else:
			print("❌ FAILURE: Ariadne parent-to-parent thread next-link is missing.")
	else:
		print("[Sandbox] Not enough parents created to test Ariadne's Thread.")

	# 7. Cleanup test collections
	print("\n[Sandbox] Cleaning up test collections...")
	for col in [test_work_col, test_social_col]:
		client.delete_collection(col)
		print(f" - Deleted: {col}")

	print("\n=== SANDBOX MEMORY GRAPH SIMULATION COMPLETE ===\n")


if __name__ == "__main__":
	run_sandbox()
