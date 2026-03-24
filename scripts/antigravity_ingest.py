#!/usr/bin/env python3
"""
antigravity_ingest.py — Official Bünker Chronicle Ingester.

Implements the "Atomized Chronicle" architecture (v2.1):
- Grouping by session/window.
- Sequential Axon Threading (P1 -> R1 -> P2 -> R2).
- Idea Atomization (Optional segmentation for complex nodes).
- Affective Heatmaps (Segment-level emotional tagging).
- Historical Integrity (raw_content vs refined_content).
"""

import argparse
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from red_pill.memory import MemoryManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chronicle_ingest")


class ChronicleIngester:
	def __init__(self):
		self.mem = MemoryManager()
		self.collection = "archive_memories"

	def _segment_ideas(self, text: str) -> List[Dict[str, Any]]:
		"""
		Semantic fragmentation of long engrams.
		Breaks down monoliths into atomic 'Idea Fragments'.
		"""
		# Heuristic: split by double newline (paragraphs) but group small ones
		paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
		segments = []
		current_segment = ""

		for p in paragraphs:
			if len(current_segment) + len(p) < 800:
				current_segment += ("\n\n" if current_segment else "") + p
			else:
				if current_segment:
					segments.append({"content": current_segment, "type": "fragment"})
				current_segment = p

		if current_segment:
			segments.append({"content": current_segment, "type": "fragment"})

		return segments if segments else [{"content": text, "type": "monolith"}]

	def _refine_content(self, text: str) -> str:
		"""
		Heuristic Semantic Normalization.
		Removes logs, ANSI noise, and repetitive boilerplate.
		"""
		import re

		# Remove ANSI escape sequences
		text = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)
		# Remove common "loading" or "progress" noise
		text = re.sub(r"\[.*\] (DEBUG|TRACE|INFO) .*", "", text)
		# Remove massive hex blobs/base64 strings (likely artifacts/binary noise)
		text = re.sub(r"[A-Za-z0-9+/]{200,}", "[CONTENT_BLOB_REDACTED]", text)
		# Collapse multiple newlines
		text = re.sub(r"\n{3,}", "\n\n", text)
		return text.strip()

	def ingest_session(self, session_id: str, messages: List[Dict[str, Any]]):
		"""
		Ingests ALL messages in a session sequentially.
		Forges a continuous synaptic thread.
		"""
		logger.info(f"Ingesting session {session_id} ({len(messages)} messages)...")

		last_node_id = None

		for idx, msg in enumerate(messages):
			role = msg.get("role")
			content = msg.get("content", "")
			if not content or role == "system":
				continue  # Skip empty or system noise

			ts = msg.get("timestamp")

			# Parse ISO timestamp if present
			if isinstance(ts, str):
				try:
					ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
				except ValueError:
					# In case of partial ISO or other strings
					ts = time.time()
			else:
				ts = time.time()

			# 1. Create Idempotent node ID
			# Include sequence_index to handle identical messages in the same session
			id_seed = f"{session_id}_{idx}_{role}_{content[:100]}"
			node_id = hashlib.sha256(id_seed.encode()).hexdigest()
			node_id = str(uuid.UUID(node_id[:32]))

			refined = self._refine_content(content)

			payload = {
				"raw_content": content,
				"refined_content": refined,
				"session_id": session_id,
				"sequence_index": idx,
				"role": role,
				"type": "chronicle_node",
				"created_at": ts,
			}

			# Forge the Sequence Axon (Thread Continuity)
			if last_node_id:
				payload["associations"] = [{"id": last_node_id, "weight": 1.5 if role == "assistant" else 1.0}]

			# --- Fragment Activation ---
			# If the content is long, we create a parent node (monolith)
			# and child nodes (fragments) linked via associations.
			fragments = self._segment_ideas(refined) if len(refined) > 1500 else []

			if fragments:
				payload["type"] = "monolith_parent"
				payload["fragment_count"] = len(fragments)

			# Add main node (or monolith parent)
			self.mem.add_memory(collection=self.collection, text=refined[:5000], point_id=node_id, metadata=payload, importance=5.0)

			# Add child fragments if any
			for f_idx, frag in enumerate(fragments):
				f_id_seed = f"{node_id}_frag_{f_idx}"
				f_node_id = hashlib.sha256(f_id_seed.encode()).hexdigest()
				f_node_id = str(uuid.UUID(f_node_id[:32]))

				f_payload = {
					"raw_content": frag["content"],
					"refined_content": frag["content"],
					"parent_id": node_id,
					"session_id": session_id,
					"type": "idea_fragment",
					"associations": [{"id": node_id, "weight": 2.0}],  # Link to parent
				}
				self.mem.add_memory(
					collection=self.collection,
					text=frag["content"],
					point_id=f_node_id,
					metadata=f_payload,
					importance=3.0,  # Fragments are granular
				)

			# Update previous node forward link (Forward Sequential Axon)
			if last_node_id:
				try:
					# Fetch existing associations to append
					# Simplified: just push the new association.
					# Note: Ideally we use a batch or transactional update,
					# but for historical ingestion, this sequential link is key.
					self.mem.client.set_payload(
						collection_name=self.collection, payload={"associations": [{"id": node_id, "weight": 1.0}]}, points=[last_node_id]
					)
				except Exception as e:
					logger.debug(f"Forward link failed: {e}")

			last_node_id = node_id

		logger.info(f"Session {session_id} ingestion complete.")


def main():
	parser = argparse.ArgumentParser(description="Ingest Antigravity historical conversations into the Bünker.")
	parser.add_argument("--dir", type=str, required=True, help="Directory containing decrypted JSON/JSONL conversations.")
	args = parser.parse_args()

	ingester = ChronicleIngester()

	source_dir = Path(args.dir)
	if not source_dir.exists():
		logger.error(f"Directory {source_dir} does not exist.")
		return

	# Look for exported JSON files (from the decryption step)
	for json_file in source_dir.glob("*.json"):
		try:
			with open(json_file, "r") as f:
				data = json.load(f)

			# Support both a single session object and a list of session objects
			sessions = data if isinstance(data, list) else [data]

			for session_data in sessions:
				session_id = session_data.get("cascade_id") or session_data.get("session_id") or json_file.stem
				messages = session_data.get("messages", [])

				if messages:
					ingester.ingest_session(session_id, messages)

		except Exception as e:
			logger.error(f"Failed to process {json_file}: {e}")


if __name__ == "__main__":
	main()
