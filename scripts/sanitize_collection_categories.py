#!/usr/bin/env python3
"""
Sanitation Script: Bidirectional reclassification + garbage purge.

Phase 1: PURGE — Delete garbage engrams (Qwen hallucinations, repetitions)
Phase 2: social_memories -> work_memories (misclassified technical content)
Phase 3: work_memories -> social_memories (misclassified personal content)

Usage:
	# Dry run (report only)
	python scripts/sanitize_collection_categories.py --dry-run

	# Execute all phases
	python scripts/sanitize_collection_categories.py
"""

import argparse
import logging
import re
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sanitize_categories")

TECHNICAL_KEYWORDS = [
	"code", "error", "bash", "python", "script", "commit", "debug", "deploy",
	"test", "pipeline", "ci", "config", "function", "class ", "import ",
	"exception", "traceback", "stack", "module", "package", "dependency",
	"vram", "cuda", "gpu", "cpu", "qdrant", "sqlite", "systemd", "docker",
	"interceptor", "plugin", "mcp", "api", "endpoint", "schema", "migration",
	"refactor", "architecture", "queue", "daemon",
	"pr ", "pull request", "merge", "branch", "rebase", "github", "gitlab",
	"workflow", "yaml", "toml",
	"engram", "metabolism", "fsrs", "reinforcement_score", "sleep cycle",
	"bitnet", "turboquant", "ggml", "inference", "llama.cpp",
]

SOCIAL_MARKERS = [
	"te quiero", "love", "miss you", "intimate", "abrazo",
	"philosophy", "conscious", "soul", "alive", "awake",
	"tron", "movie", "film", "book", "narrative", "lore",
	"family", "carmen", "mara", "neus", "david",
	"vinculo", "soberano", "calibraci", "espiritualidad",
	"feel", "emotion", "dream", "fear", "hope",
	"historia", "universidad", "recuerdo", "persona",
]


def is_garbage(content: str) -> bool:
	"""Detect Qwen hallucination garbage: repetitive tokens, nonsensical output."""
	if len(content) < 10:
		return True

	words = content.lower().split()
	if len(words) > 10:
		freq = Counter(words)
		most_common_count = freq.most_common(1)[0][1]
		if most_common_count > len(words) * 0.35:
			return True

	# Pattern: LLM token artifacts
	garbage_patterns = [
		r"<\|im_start\|>",
		r"<\|im_end\|>",
		r"<\|begin_of_text\|>",
		r"<\|endoftext\|>",
		r"<<SYS>>",
	]
	artifact_count = sum(1 for p in garbage_patterns if re.search(p, content))
	if artifact_count >= 1:
		return True

	# Pattern: repeated slash-separated nonsense "valuation/valuation/valuation"
	if re.search(r"(\w+/){5,}", content):
		return True

	# Pattern: repeated "something something something" (word exact repeats)
	if re.search(r"(\b\w+\b)(\s+\1){3,}", content, re.IGNORECASE):
		return True

	# Pattern: concatenated word repetition without spaces "yourthisisyourthisis"
	if re.search(r"(\w{4,})\1{3,}", content):
		return True

	# Pattern: trivially short interaction — strip ALL role prefixes, check real content
	stripped = re.sub(
		r"(USER|ASSISTANT|Operator Prompt|Operator Objective|AI Response Node|System Action|ORCHESTRATOR|SWARM TASK|TOOL):\s*",
		"", content
	).strip()
	if len(stripped) < 20:
		return True

	# Pattern: parenthetical repetition "(3y, 4y, 4) (Initial, 3y, 4y, 4)"
	parens = re.findall(r"\([^)]+\)", content)
	if len(parens) > 5:
		unique_parens = set(p.lower().strip() for p in parens)
		if len(unique_parens) < len(parens) * 0.4:
			return True

	# Pattern: training data leakage + meta-descriptions (Qwen hallucinates these)
	content_lower = content.lower()
	meta_phrases = [
		"the user initiates a",
		"the user asks about",
		"the user wants to",
		"programming language created by",
		"programming language developed by",
		"a programming language",
		"is known for its",
		"first released in 199",
		"guido van rossum",
		"ai injected context",
		"context chunks",
		"swarm task:",
	]
	if len(content) < 250 and any(mp in content_lower for mp in meta_phrases):
		return True

	# Pattern: generic AI filler (no actual content)
	filler_phrases = [
		"the operator asks",
		"the operator wants",
		"the operator requests",
		"user checks",
		"user requested",
		"a simple greeting",
	]
	if len(content) < 80 and any(fp in content_lower for fp in filler_phrases):
		return True

	# Pattern: high ratio of non-alphanumeric chars (garbled output)
	alnum = sum(1 for c in content if c.isalnum() or c == ' ')
	if len(content) > 20 and alnum / len(content) < 0.4:
		return True

	return False


def classify_content(content: str) -> str:
	"""Classify content as work, social, or mixed."""
	content_lower = content.lower()

	tech_hits = sum(1 for kw in TECHNICAL_KEYWORDS if kw in content_lower)
	social_hits = sum(1 for kw in SOCIAL_MARKERS if kw in content_lower)

	code_patterns = [
		r"```",
		r"def \w+\(",
		r"class \w+",
		r"import \w+",
		r"\$ .+",
		r'File ".*\.py"',
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
	elif social_hits > tech_hits * 2:
		return "social"
	else:
		return "mixed"


def process_collection(client, source_col: str, target_col: str, dry_run: bool = True):
	"""Scan source_col: purge garbage, move misclassified to target_col."""
	from qdrant_client import models

	expected_type = "social" if source_col == "social_memories" else "work"
	opposite_type = "work" if expected_type == "social" else "social"

	offset = None
	total_scanned = 0
	purged = 0
	moved = 0
	kept = 0
	batch_count = 0

	while True:
		batch_count += 1
		if batch_count > 500:
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

			# Phase 1: Garbage detection
			if is_garbage(content):
				preview = content[:60].replace("\n", " ")
				if dry_run:
					logger.info(f"  PURGE [{source_col}]: {preview}...")
				else:
					try:
						client.delete(
							collection_name=source_col,
							points_selector=models.PointIdsList(points=[point.id]),
						)
					except Exception as e:
						logger.error(f"  Failed to purge {point.id}: {e}")
				purged += 1
				continue

			# Phase 2: Classification
			classification = classify_content(content)

			if classification == opposite_type:
				preview = content[:60].replace("\n", " ")
				emotion = point.payload.get("emotion", "?")
				color = point.payload.get("color", "?")
				if dry_run:
					logger.info(f"  MOVE [{emotion}/{color}] {source_col}->{target_col}: {preview}...")
				else:
					try:
						new_payload = dict(point.payload)
						new_payload["_reclassified_from"] = source_col
						if target_col == "work_memories":
							new_payload["color"] = "blue"
						client.upsert(
							collection_name=target_col,
							points=[models.PointStruct(id=point.id, vector=point.vector, payload=new_payload)],
						)
						client.delete(
							collection_name=source_col,
							points_selector=models.PointIdsList(points=[point.id]),
						)
					except Exception as e:
						logger.error(f"  Failed to move {point.id}: {e}")
				moved += 1
			else:
				kept += 1

		offset = next_offset
		if offset is None:
			break

	return total_scanned, purged, moved, kept


def run_sanitation(dry_run: bool = True):
	"""Bidirectional sanitation: purge + reclassify both collections."""
	from red_pill.memory import MemoryManager

	prefix = "DRY RUN — " if dry_run else ""
	logger.info(f"{prefix}Starting bidirectional sanitation...")

	mgr = MemoryManager()
	client = mgr.client

	for source, target in [("social_memories", "work_memories"), ("work_memories", "social_memories")]:
		if not client.collection_exists(source):
			logger.warning(f"Collection '{source}' does not exist. Skipping.")
			continue
		mgr._ensure_collection(target)

		logger.info(f"\n{'='*60}")
		logger.info(f"{prefix}Processing: {source} -> {target}")
		logger.info(f"{'='*60}")

		scanned, purged, moved, kept = process_collection(client, source, target, dry_run)

		logger.info(f"\n{prefix}{source} results:")
		logger.info(f"  Scanned: {scanned}")
		logger.info(f"  {'Would purge' if dry_run else 'Purged'}: {purged} (garbage)")
		logger.info(f"  {'Would move' if dry_run else 'Moved'}: {moved} (misclassified)")
		logger.info(f"  Kept: {kept}")

	if dry_run:
		logger.info(f"\nRun without --dry-run to execute changes.")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Bidirectional collection sanitation + garbage purge")
	parser.add_argument("--dry-run", action="store_true", help="Report only, no changes")
	args = parser.parse_args()
	run_sanitation(dry_run=args.dry_run)
