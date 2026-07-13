#!/usr/bin/env python3
"""
Re-embed stored engrams with the current EMBEDDING_MODEL.

Changing the embedding model (e.g. English-only all-MiniLM-L6-v2 → multilingual
paraphrase-multilingual-MiniLM-L12-v2) leaves every stored vector computed by the
OLD model, so recall degrades until they are recomputed. Same 384-dim size means
NO schema migration — only the vectors change, payloads and ids are untouched.

Safe by default:
- --dry-run is the DEFAULT. Pass --execute to actually write.
- Resumable: a cursor is saved after every batch; re-running continues.
- archive_memories (huge) is excluded unless explicitly listed.

The operator runs `--execute` with the system idle. Do not run it from tests.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [REEMBED] %(message)s")
logger = logging.getLogger("reembed")

DEFAULT_COLLECTIONS = [
	"work_memories",
	"social_memories",
	"directive_memories",
	"skill_memories",
	"story_memories",
	"core_directives",
	"interaction_memories",
]


def get_cursor_path() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / "reembed_cursor.json"


def load_cursor(path: Path) -> Dict[str, Any]:
	if path.exists():
		try:
			return dict(json.loads(path.read_text(encoding="utf-8")))
		except Exception as e:
			logger.warning(f"Unreadable cursor {path}: {e}. Starting fresh.")
	return {}


def save_cursor(path: Path, cursor: Dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(".json.tmp")
	tmp.write_text(json.dumps(cursor), encoding="utf-8")
	tmp.replace(path)


def reembed_collection(
	client: Any,
	engine: Any,
	collection: str,
	batch_size: int,
	cursor: Dict[str, Any],
	cursor_path: Optional[Path],
	dry_run: bool,
) -> Dict[str, int]:
	"""Recompute vectors for one collection. Returns {reembedded, skipped}."""
	from qdrant_client.http import models

	if not client.collection_exists(collection):
		logger.info(f"{collection}: does not exist, skipping.")
		return {"reembedded": 0, "skipped": 0}

	if dry_run:
		total = client.count(collection_name=collection, exact=True).count
		logger.info(f"[DRY-RUN] {collection}: {total} points would be re-embedded.")
		return {"reembedded": 0, "skipped": 0}

	reembedded = 0
	skipped = 0
	offset = cursor.get(collection)

	while True:
		records, next_offset = client.scroll(
			collection_name=collection,
			limit=batch_size,
			offset=offset,
			with_payload=["content"],
			with_vectors=False,
		)
		if not records:
			break

		point_vectors: List[Any] = []
		for rec in records:
			content = (rec.payload or {}).get("content")
			if not content:
				skipped += 1
				continue
			vector = engine.get_vector(content)
			point_vectors.append(models.PointVectors(id=rec.id, vector=vector))

		if point_vectors:
			client.update_vectors(collection_name=collection, points=point_vectors)
			reembedded += len(point_vectors)

		# Persist progress after every batch so a crash/kill can resume.
		cursor[collection] = next_offset
		if cursor_path is not None:
			save_cursor(cursor_path, cursor)

		if next_offset is None:
			break
		offset = next_offset
		logger.info(f"{collection}: {reembedded} re-embedded, {skipped} skipped (no content)...")

	# Collection done → clear its cursor entry.
	cursor.pop(collection, None)
	if cursor_path is not None:
		save_cursor(cursor_path, cursor)
	logger.info(f"{collection}: DONE. {reembedded} re-embedded, {skipped} skipped.")
	return {"reembedded": reembedded, "skipped": skipped}


def main() -> None:
	parser = argparse.ArgumentParser(description="Re-embed stored engrams with the current EMBEDDING_MODEL.")
	parser.add_argument("--collections", default=",".join(DEFAULT_COLLECTIONS), help="Comma-separated collections. archive_memories excluded by default.")
	parser.add_argument("--execute", action="store_true", help="Actually write vectors. Without it, runs a dry-run.")
	parser.add_argument("--batch-size", type=int, default=256)
	parser.add_argument("--reset-cursor", action="store_true", help="Ignore any saved resume cursor.")
	args = parser.parse_args()

	from qdrant_client import QdrantClient

	import red_pill.config as cfg
	from red_pill.core.embeddings import EmbeddingEngine

	collections = [c.strip() for c in args.collections.split(",") if c.strip()]
	dry_run = not args.execute
	cursor_path = get_cursor_path()
	cursor = {} if args.reset_cursor else load_cursor(cursor_path)

	logger.info(f"Model: {cfg.EMBEDDING_MODEL} | mode: {'DRY-RUN' if dry_run else 'EXECUTE'} | collections: {collections}")
	if "archive_memories" in collections:
		logger.warning("archive_memories included explicitly — this is very large.")

	client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
	engine = EmbeddingEngine()

	totals = {"reembedded": 0, "skipped": 0}
	for collection in collections:
		res = reembed_collection(client, engine, collection, args.batch_size, cursor, cursor_path, dry_run)
		totals["reembedded"] += res["reembedded"]
		totals["skipped"] += res["skipped"]

	logger.info(f"Complete. Total re-embedded: {totals['reembedded']}, skipped (no content): {totals['skipped']}.")


if __name__ == "__main__":
	main()
