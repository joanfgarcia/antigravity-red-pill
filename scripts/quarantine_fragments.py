#!/usr/bin/env python3
"""
Quarantine oversized-engram fragments (_is_fragment=True) out of the live
memory collections into archive_memories.

These are verbatim code/log shrapnel chunked from oversized engrams, stored
immune=True so the Bayesian engine never forgets them — they bury the real
distilled hubs. Hito 2 already hides them from search; this is storehouse
hygiene: move them to archive_memories (searchable only via deep archive tools)
and drop their immune flag.

Safe by default:
  * --dry-run is the DEFAULT. Pass --execute to actually move.
  * Move order is upsert → verify → delete, so a crash never loses data.
  * Reports how many parent engrams may be orphaned (the janitor's
    orphaned-parents sweep will clean those; this is just a heads-up).

The operator runs `--execute` AFTER a Qdrant snapshot. Do not run it from tests.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import Counter
from typing import Any, Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [QUARANTINE] %(message)s")
logger = logging.getLogger("quarantine")

ARCHIVE = "archive_memories"


def _fragment_filter():
	from qdrant_client.http import models

	return models.Filter(must=[models.FieldCondition(key="_is_fragment", match=models.MatchValue(value=True))])


def dry_run_collection(client: Any, collection: str) -> Dict[str, Any]:
	"""Count fragments and their parent distribution without writing anything."""
	if not client.collection_exists(collection):
		logger.info(f"{collection}: does not exist, skipping.")
		return {"fragments": 0, "orphan_parents": 0}

	parents: Counter = Counter()
	total = 0
	offset = None
	while True:
		records, offset = client.scroll(
			collection_name=collection, scroll_filter=_fragment_filter(), limit=256, offset=offset, with_payload=["parent_id"], with_vectors=False
		)
		for rec in records:
			total += 1
			parents[(rec.payload or {}).get("parent_id")] += 1
		if offset is None:
			break

	logger.info(f"[DRY-RUN] {collection}: {total} fragments across {len(parents)} distinct parents.")
	for parent_id, cnt in parents.most_common(20):
		logger.info(f"    parent={parent_id}: {cnt} fragments")
	return {"fragments": total, "orphan_parents": len(parents)}


def quarantine_collection(client: Any, collection: str, batch_size: int, now: float) -> Dict[str, Any]:
	"""Move fragments to archive_memories. Returns {moved, failed, orphan_parents}."""
	from qdrant_client.http import models

	if not client.collection_exists(collection):
		logger.info(f"{collection}: does not exist, skipping.")
		return {"moved": 0, "failed": 0, "orphan_parents": 0}
	if not client.collection_exists(ARCHIVE):
		logger.error(f"{ARCHIVE} does not exist — cannot quarantine. Create it first.")
		return {"moved": 0, "failed": 0, "orphan_parents": 0}

	moved = 0
	failed = 0
	touched_parents: set = set()
	offset = None

	while True:
		records, offset = client.scroll(
			collection_name=collection, scroll_filter=_fragment_filter(), limit=batch_size, offset=offset, with_payload=True, with_vectors=True
		)
		if not records:
			break

		ids = [rec.id for rec in records]
		points = []
		for rec in records:
			payload = dict(rec.payload or {})
			payload.update({"immune": False, "_quarantined_from": collection, "_quarantined_at": now})
			points.append(models.PointStruct(id=rec.id, vector=rec.vector, payload=payload))
			touched_parents.add(payload.get("parent_id"))

		client.upsert(collection_name=ARCHIVE, points=points)

		# Verify the upsert landed BEFORE deleting the source — never lose data.
		retrieved = client.retrieve(collection_name=ARCHIVE, ids=ids, with_payload=False, with_vectors=False)
		if len(retrieved) == len(ids):
			client.delete(collection_name=collection, points_selector=models.PointIdsList(points=ids))
			moved += len(ids)
		else:
			failed += len(ids)
			logger.error(f"{collection}: upsert verification failed for a batch ({len(retrieved)}/{len(ids)}). Source NOT deleted.")

		logger.info(f"{collection}: {moved} moved, {failed} failed...")
		if offset is None:
			break

	orphan_parents = len(touched_parents - {None})
	logger.info(f"{collection}: DONE. {moved} moved, {failed} failed. ~{orphan_parents} parents may now be orphaned (janitor will sweep).")
	return {"moved": moved, "failed": failed, "orphan_parents": orphan_parents}


def main() -> None:
	parser = argparse.ArgumentParser(description="Quarantine _is_fragment engrams into archive_memories.")
	parser.add_argument("--execute", action="store_true", help="Actually move. Without it, runs a dry-run.")
	parser.add_argument("--include-social", action="store_true", help="Also process social_memories (default: only work_memories).")
	parser.add_argument("--batch-size", type=int, default=128)
	args = parser.parse_args()

	from qdrant_client import QdrantClient

	import red_pill.config as cfg

	collections = ["work_memories"]
	if args.include_social:
		collections.append("social_memories")

	dry_run = not args.execute
	logger.info(f"mode: {'DRY-RUN' if dry_run else 'EXECUTE'} | collections: {collections}")

	client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY)
	now = time.time()

	totals = {"moved": 0, "failed": 0}
	for collection in collections:
		if dry_run:
			dry_run_collection(client, collection)
		else:
			res = quarantine_collection(client, collection, args.batch_size, now)
			totals["moved"] += res["moved"]
			totals["failed"] += res["failed"]

	if not dry_run:
		logger.info(f"Complete. Total moved: {totals['moved']}, failed: {totals['failed']}.")


if __name__ == "__main__":
	main()
