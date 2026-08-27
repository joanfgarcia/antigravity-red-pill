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

from red_pill.core.storage import StorageEngine
from red_pill.memory import MemoryManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chronicle_ingest")


class ChronicleIngester:
	def __init__(self):
		self.mem = MemoryManager()
		self.collection = "archive_memories"
		StorageEngine().ensure_collection(self.collection)

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
		Delegates to the shared module (RFC-002 §5.2) so the ingester and the
		Memento renderer produce byte-identical cleaned text.
		"""
		from red_pill.memento.clean import normalize_noise

		return normalize_noise(text)

	def _evict_previous_copies(self, session_id: str, idx: int, role: str, node_id: str) -> None:
		"""Retira las copias previas de este mensaje lógico (otros ids) y sus fragments.

		Best-effort: un fallo aquí no aborta la ingesta — el colapso nocturno de
		`dedup_archive_memories.py` es la red de seguridad.
		"""
		from qdrant_client.http import models

		try:
			key_filter = models.Filter(
				must=[
					models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id)),
					models.FieldCondition(key="sequence_index", match=models.MatchValue(value=idx)),
					models.FieldCondition(key="role", match=models.MatchValue(value=role)),
				]
			)
			old_points, _ = self.mem.client.scroll(self.collection, scroll_filter=key_filter, limit=64, with_payload=False)
			old_ids = [str(p.id) for p in old_points if str(p.id) != node_id]
			if not old_ids:
				return
			self.mem.client.delete(
				self.collection,
				points_selector=models.FilterSelector(
					filter=models.Filter(must=[models.FieldCondition(key="parent_id", match=models.MatchAny(any=old_ids))])
				),
				wait=True,
			)
			self.mem.client.delete(self.collection, points_selector=old_ids, wait=True)
		except Exception as e:
			logger.debug(f"Evict of previous copies failed for {session_id}#{idx}: {e}")

	def ingest_session(self, session_id: str, messages: List[Dict[str, Any]], originator: str = "antigravity"):
		"""
		Ingests ALL messages in a session sequentially.
		Forges a continuous synaptic thread.

		`originator` identifica la fuente (antigravity | claude_code | opencode);
		el session_id ya debe venir namespaced por el plugin de fuente.
		"""
		logger.info(f"Ingesting session {session_id} ({len(messages)} messages, source={originator})...")

		last_node_id = None

		for idx, msg in enumerate(messages):
			# --- Power Throttling Logic (Protocol 770) ---
			import psutil

			if hasattr(psutil, "sensors_battery"):
				battery = psutil.sensors_battery()
				if battery and battery.power_plugged is False:
					# Hard Halt if battery is critical
					if battery.percent < 20:
						logger.warning(f"CRITICAL BATTERY ({battery.percent}%). Emergency shutdown of ingestion.")
						return

					# Soft Throttle: Sleep to cool down and save power
					logger.debug(f"Power Save Mode: Throttling ingestion (Battery @ {battery.percent}%)...")
					time.sleep(1.0)  # Introduce latency to drop CPU usage

			role = msg.get("role")

			content = msg.get("content", "")
			if content:
				content = content.replace("\x00", "")

			if not content or role == "system":
				continue  # Skip empty or system noise

			ts = msg.get("timestamp")

			# Parse ISO timestamp if present; epoch numérico (opencode) pasa directo
			if isinstance(ts, str):
				try:
					ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
				except ValueError:
					# In case of partial ISO or other strings
					ts = time.time()
			elif isinstance(ts, (int, float)) and not isinstance(ts, bool):
				ts = float(ts)
			else:
				ts = time.time()

			# 1. Create Idempotent node ID
			# Include sequence_index to handle identical messages in the same session
			id_seed = f"{session_id}_{idx}_{role}_{content[:100]}"
			node_id = hashlib.sha256(id_seed.encode()).hexdigest()
			node_id = str(uuid.UUID(node_id[:32]))

			refined = self._refine_content(content)

			payload = {
				"raw_content": content[:1024],
				"refined_content": refined[:1024],
				"session_id": session_id,
				"sequence_index": idx,
				"role": role,
				"type": "chronicle_node",
				"created_at": ts,
				"originator": originator,
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

			# Self-healing: el id incluye content[:100] y el contenido DERIVA entre
			# exportaciones (telemetría, timestamps) — sin esto, cada re-ingesta de
			# una sesión crecida acuña un id nuevo para el mismo mensaje y la
			# colección se infla (725K puntos para 232 sesiones, jul 2026).
			self._evict_previous_copies(session_id, idx, role, node_id)

			# Add main node (or monolith parent)
			self.mem.add_memory(collection=self.collection, text=refined[:5000], point_id=node_id, metadata=payload, importance=5.0)

			# Add child fragments if any
			for f_idx, frag in enumerate(fragments):
				f_id_seed = f"{node_id}_frag_{f_idx}"
				f_node_id = hashlib.sha256(f_id_seed.encode()).hexdigest()
				f_node_id = str(uuid.UUID(f_node_id[:32]))

				f_payload = {
					"raw_content": frag["content"][:1024],
					"refined_content": frag["content"][:1024],
					"parent_id": node_id,
					"session_id": session_id,
					"type": "idea_fragment",
					"originator": originator,
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
				originator = session_data.get("originator", "antigravity")

				if messages:
					ingester.ingest_session(session_id, messages, originator=originator)

		except Exception as e:
			logger.error(f"Failed to process {json_file}: {e}")


if __name__ == "__main__":
	main()
