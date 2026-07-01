import logging
import time
import uuid
from typing import Any, Dict, List

from qdrant_client import QdrantClient
from qdrant_client.http import models

import red_pill.config as cfg
from red_pill.core.embeddings import EmbeddingEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("parent_child_migrate")


def run_migration():
	print("\n=== INITIATING LIVE BÜNKER PARENT-CHILD MIGRATION ===")

	client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
	embedding_engine = EmbeddingEngine()

	collections = ["work_memories", "social_memories"]

	total_migrated_groups = 0
	total_migrated_children = 0
	start_time = time.time()

	for col in collections:
		if not client.collection_exists(col):
			print(f"[Migration] Collection {col} does not exist. Skipping.")
			continue

		print(f"\n[Migration] Scrolling all engrams in {col}...")

		# Scroll all sequence_chunk and synthesis_hub engrams
		offset = None
		all_records = []
		while True:
			# We fetch points.
			records, next_offset = client.scroll(collection_name=col, limit=100, offset=offset, with_payload=True, with_vectors=True)
			all_records.extend(records)
			if next_offset is None:
				break
			offset = next_offset

		print(f"[Migration] Retrieved {len(all_records)} total points from {col}.")

		# Filter sequence_chunk and synthesis_hub engrams that have source_buffer_id but NO parent_id
		target_engrams = []
		for r in all_records:
			payload = r.payload or {}
			# Check if parent_id exists (to make migration idempotent)
			if "parent_id" in payload:
				continue

			l_phase = payload.get("lazarus_phase")
			sb_id = payload.get("source_buffer_id")

			if sb_id and l_phase in ("sequence_chunk", "synthesis_hub"):
				target_engrams.append(r)

		print(f"[Migration] Found {len(target_engrams)} engrams needing migration in {col}.")
		if not target_engrams:
			continue

		# Group target engrams by source_buffer_id
		grouped: Dict[str, List[Any]] = {}
		for r in target_engrams:
			sb_id = str(r.payload["source_buffer_id"])
			if sb_id not in grouped:
				grouped[sb_id] = []
			grouped[sb_id].append(r)

		print(f"[Migration] Grouped into {len(grouped)} unique parent conversation sessions.")

		# Thread State / last raw parent tracking per collection
		from red_pill.metabolism.sleep import _load_thread_state, _save_thread_state

		thread_state = _load_thread_state()
		prev_parent_key = f"last_raw_parent_{col}"
		last_parent_id = thread_state.get(prev_parent_key)

		for sb_id, child_nodes in grouped.items():
			parent_uuid = str(uuid.uuid4())

			# Concatenate content of child chunks to synthesize parent verbatim
			synthesized_text = ""
			child_ids = []

			# Sort child nodes by created_at or chunk_index if available to preserve ordering
			child_nodes.sort(key=lambda x: (x.payload.get("chunk_index", 0), x.payload.get("created_at", 0)))

			for i, child in enumerate(child_nodes):
				child_ids.append(str(child.id))
				content = child.payload.get("content", "")
				synthesized_text += f"Chunk {i + 1}: {content}\n\n"

			# Generate vector embedding for synthetic parent engram
			parent_vector = embedding_engine.get_vector(synthesized_text)

			# Setup parent payload
			parent_payload = {
				"content": synthesized_text,
				"importance": 5.0,
				"reinforcement_score": 10.0,
				"created_at": child_nodes[0].payload.get("created_at", time.time()),
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

			# Ariadne parent threading
			if last_parent_id:
				parent_payload["prev_raw_parent"] = last_parent_id

			# Upsert parent engram
			client.upsert(collection_name=col, points=[models.PointStruct(id=parent_uuid, payload=parent_payload, vector=parent_vector)])

			# Thread update forward connection
			if last_parent_id:
				client.set_payload(collection_name=col, payload={"next_raw_parent": parent_uuid}, points=[last_parent_id])

			last_parent_id = parent_uuid

			# Update parent_id link on children (both vector and payload remain preserved)
			for child in child_nodes:
				client.set_payload(collection_name=col, payload={"parent_id": parent_uuid}, points=[child.id])
				total_migrated_children += 1

			total_migrated_groups += 1

		# Save final thread state for this collection
		if last_parent_id:
			thread_state[prev_parent_key] = last_parent_id
			_save_thread_state(thread_state)

	elapsed = time.time() - start_time
	print("\n" + "=" * 50)
	print("MIGRATION COMPLETE")
	print("=" * 50)
	print(f"Total parent nodes created:   {total_migrated_groups}")
	print(f"Total child nodes linked:     {total_migrated_children}")
	print(f"Total elapsed migration time: {elapsed:.2f} seconds")
	print("=" * 50 + "\n")


if __name__ == "__main__":
	run_migration()
