#!/usr/bin/env python3
"""
Chronicle Distiller (The Scribe) - Phase 3 Cognitive Refinement
Uses the local Edge Engine to perform semantic distillation on high-value points.
"""

import logging
import os

import requests
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from red_pill.core.paths import get_config_dir

env_path = get_config_dir() / ".env"
if env_path.exists():
	load_dotenv(env_path)
else:
	load_dotenv()

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Distiller")


# Config
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_KEY = os.getenv("QDRANT_API_KEY")
EDGE_ENGINE_URL = "http://localhost:8760/v1/chat/completions"
COLLECTION_NAME = "archive_memories"
BATCH_SIZE = 50
MIN_CONTENT_LENGTH = 500

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_KEY)

DISTILL_PROMPT = """Role: Bünker Scribe.
Mission: Distill the essence of this historical memory node.
Context: You are summarizing a dialogue part (User prompt or Assistant response) from an advanced agentic coding session.

Rules:
- Extract core technical decisions, key code snippets, or philosophical insights.
- Analyze the underlying emotional state (mood, sentiment) and philosophical load of the interaction.
- Remove conversational filler (greetings, politeness, noise).
- Keep it concise but dense with meaning.
- Output ONLY the distilled text. No "Here is the summary".
- Max length: 512 characters.

Content to Distill:
{content}
"""


def distill_text(content: str) -> str:
	"""Sends content to the local Edge Engine for distillation."""
	try:
		payload = {
			"model": "samantha-mistral-instruct-7b.i1-Q4_K_M.gguf",
			"messages": [
				{
					"role": "system",
					"content": "You are Samantha, the Bünker Scribe. Distill the essence, emotional state, and philosophical load into high-density knowledge.",
				},
				{"role": "user", "content": DISTILL_PROMPT.format(content=content[:4000])},  # Cap input
			],
			"temperature": 0.1,
			"max_tokens": 256,
		}
		response = requests.post(EDGE_ENGINE_URL, json=payload, timeout=60)
		response.raise_for_status()
		return response.json()["choices"][0]["message"]["content"].strip()
	except Exception as e:
		logger.error(f"Distillation failed: {e}")
		return content  # Return original on failure


def process_batch():
	"""Fetches high-value points and distills them."""
	logger.info(f"Scanning {COLLECTION_NAME} for points requiring distillation...")

	# Filter: Assistant or User nodes, long enough to benefit from distillation,
	# and haven't been LLM-distilled yet (heuristic: refined_content is same as raw_content or empty?)
	# For now, let's just find Assistant nodes that are long.

	offset = None
	processed_count = 0

	while True:
		points, offset = client.scroll(
			collection_name=COLLECTION_NAME,
			scroll_filter=Filter(
				must=[
					FieldCondition(key="role", match=MatchValue(value="assistant")),
				],
				must_not=[
					FieldCondition(key="cognitive_status", match=MatchValue(value="distilled")),
				],
			),
			limit=BATCH_SIZE,
			offset=offset,
			with_payload=True,
			with_vectors=False,
		)

		if not points:
			logger.info("No more high-value nodes found. Distillation complete.")
			break

		for point in points:
			payload = point.payload or {}
			raw_content = payload.get("raw_content", "")

			# Skip short nodes (already atomic)
			if len(raw_content) < MIN_CONTENT_LENGTH:
				# Mark as skipped to avoid re-scanning
				client.set_payload(collection_name=COLLECTION_NAME, payload={"cognitive_status": "skipped_too_short"}, points=[point.id])
				continue

			logger.info(f"Distilling Point {point.id} (Len: {len(raw_content)})...")
			summary = distill_text(raw_content)

			# Update Point Payload
			client.set_payload(
				collection_name=COLLECTION_NAME,
				payload={"refined_content": summary, "cognitive_status": "distilled", "distillation_model": "samantha-mistral-instruct-7b"},
				points=[point.id],
			)
			processed_count += 1

		logger.info(f"Batch completed. Total processed this session: {processed_count}")

	logger.info(f"Distillation session finished. Total nodes refined: {processed_count}")


if __name__ == "__main__":
	process_batch()
