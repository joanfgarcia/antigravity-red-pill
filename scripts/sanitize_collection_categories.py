#!/usr/bin/env python3
"""
Sanitation Script: Reclassify misplaced engrams in social_memories.

Problem: Before v6.3.8, the sleep cycle used a crude 6-keyword heuristic
to classify engrams. This caused ~50% of technical conversations
(architecture, VRAM, infrastructure, roadmap) to end up in social_memories
because they didn't contain "code", "error", "bash", etc.

Solution: Scan social_memories for technical content and move it to work_memories.

Usage:
	# Dry run (report only)
	python scripts/sanitize_collection_categories.py --dry-run

	# Execute moves
	python scripts/sanitize_collection_categories.py

	# Custom keywords
	python scripts/sanitize_collection_categories.py --extra-keywords "terraform,docker"
"""

import argparse
import logging
import re
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sanitize_categories")

# Extended keyword list for detecting technical content
TECHNICAL_KEYWORDS = [
	# Programming
	"code", "error", "bash", "python", "script", "commit", "debug", "deploy",
	"test", "pipeline", "ci", "config", "function", "class ", "import ",
	"exception", "traceback", "stack", "module", "package", "dependency",
	# Infrastructure
	"vram", "cuda", "gpu", "cpu", "qdrant", "sqlite", "systemd", "docker",
	"container", "nginx", "firewall", "ssh", "ssl", "tls", "dns",
	# Architecture
	"interceptor", "plugin", "mcp", "api", "endpoint", "schema", "migration",
	"refactor", "architecture", "microservice", "queue", "daemon",
	# Git/CI
	"pr ", "pull request", "merge", "branch", "rebase", "github", "gitlab",
	"workflow", "action", "yaml", "toml", "json schema",
	# Red Pill specific
	"engram", "metabolism", "fsrs", "reinforcement_score", "sleep cycle",
	"bitnet", "turboquant", "ggml", "inference", "llama.cpp",
]

# Keywords that indicate social/emotional content (anti-patterns)
SOCIAL_MARKERS = [
	"feel", "emotion", "love", "miss you", "intimate", "dream",
	"philosophy", "conscious", "soul", "alive", "awake",
	"tron", "movie", "film", "book", "story", "narrative",
	"family", "carmen", "mara", "neus",
	"morning", "night", "sleep", "wake up",
]


def classify_content(content: str) -> str:
	"""Classify content as work, social, or mixed based on keyword analysis."""
	content_lower = content.lower()

	tech_hits = sum(1 for kw in TECHNICAL_KEYWORDS if kw in content_lower)
	social_hits = sum(1 for kw in SOCIAL_MARKERS if kw in content_lower)

	# Also check for code patterns
	code_patterns = [
		r"```",					# Code blocks
		r"def \w+\(",			  # Python functions
		r"class \w+",			 # Python classes
		r"import \w+",			# Imports
		r"\$ .+",				  # Shell commands
		r"File \".*\.py\"",	   # Python tracebacks
		r"https?://",			 # URLs (usually technical)
	]
	for pattern in code_patterns:
		if re.search(pattern, content):
			tech_hits += 2

	if tech_hits >= 3 and social_hits <= 1:
		return "work"
	elif social_hits >= 3 and tech_hits <= 1:
		return "social"
	elif tech_hits > social_hits * 2:
		return "work"
	else:
		return "mixed"  # Genuinely mixed — leave in social_memories


def run_sanitation(dry_run: bool = True, extra_keywords: list | None = None):
	"""Scan social_memories and reclassify misplaced technical engrams."""
	# Import here to allow --help without dependencies
	from red_pill.memory import MemoryManager

	if extra_keywords:
		TECHNICAL_KEYWORDS.extend(extra_keywords)

	logger.info(f"{'DRY RUN — ' if dry_run else ''}Starting social_memories sanitation...")
	logger.info(f"Technical keywords: {len(TECHNICAL_KEYWORDS)}, Social markers: {len(SOCIAL_MARKERS)}")

	mgr = MemoryManager()
	client = mgr.client

	source_col = "social_memories"
	target_col = "work_memories"

	if not client.collection_exists(source_col):
		logger.warning(f"Collection '{source_col}' does not exist. Nothing to do.")
		return

	mgr._ensure_collection(target_col)

	# Scroll through all social_memories
	offset = None
	total_scanned = 0
	moved = 0
	mixed_kept = 0
	batch_count = 0

	while True:
		batch_count += 1
		if batch_count > 500:
			logger.warning("Safety break: too many batches.")
			break

		try:
			response = client.scroll(
				collection_name=source_col,
				limit=50,
				offset=offset,
				with_payload=True,
				with_vectors=True,
			)
		except Exception as e:
			logger.error(f"Scroll failed: {e}")
			break

		points, next_offset = response
		if not points:
			break

		for point in points:
			total_scanned += 1
			if not point.payload:
				continue

			content = str(point.payload.get("content", ""))
			if not content:
				continue

			classification = classify_content(content)

			if classification == "work":
				if dry_run:
					preview = content[:80].replace("\n", " ")
					emotion = point.payload.get("emotion", "?")
					color = point.payload.get("color", "?")
					logger.info(f"  WOULD MOVE [{emotion}/{color}]: {preview}...")
					moved += 1
				else:
					try:
						# Copy to work_memories with same vector
						from qdrant_client import models

						new_payload = dict(point.payload)
						new_payload["_reclassified_from"] = "social_memories"
						new_payload["color"] = "blue"  # Work color

						client.upsert(
							collection_name=target_col,
							points=[
								models.PointStruct(
									id=point.id,
									vector=point.vector,
									payload=new_payload,
								)
							],
						)

						# Delete from social_memories
						client.delete(
							collection_name=source_col,
							points_selector=models.PointIdsList(points=[point.id]),
						)

						moved += 1
						if moved % 10 == 0:
							logger.info(f"  Moved {moved} engrams so far...")
					except Exception as e:
						logger.error(f"  Failed to move {point.id}: {e}")

			elif classification == "mixed":
				mixed_kept += 1

		offset = next_offset
		if offset is None:
			break

	logger.info(f"\n{'DRY RUN ' if dry_run else ''}Sanitation complete:")
	logger.info(f"  Scanned: {total_scanned}")
	logger.info(f"  {'Would move' if dry_run else 'Moved'}: {moved} (technical → work_memories)")
	logger.info(f"  Kept as mixed: {mixed_kept} (genuinely social or mixed)")
	logger.info(f"  Untouched: {total_scanned - moved - mixed_kept}")

	if dry_run and moved > 0:
		logger.info(f"\nRun without --dry-run to execute {moved} moves.")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Sanitize social_memories: move technical engrams to work_memories")
	parser.add_argument("--dry-run", action="store_true", help="Report what would be moved without actually moving")
	parser.add_argument("--extra-keywords", type=str, default="", help="Comma-separated extra technical keywords")
	args = parser.parse_args()

	extras = [k.strip() for k in args.extra_keywords.split(",") if k.strip()] if args.extra_keywords else None

	run_sanitation(dry_run=args.dry_run, extra_keywords=extras)
