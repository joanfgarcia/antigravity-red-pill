"""RevisionPhase logic (Track R2): retroactive re-classification of engrams.

The R1 categorizer fix stops NEW misrouting; this sweeps the legacy backlog.
Batch-bounded per cycle, born in dry-run: it marks what it WOULD move so the
operator can inspect the plan before any engram changes collection.

Move semantics (leaf engrams only): the point is upserted under its same ID
into the correct collection and the original deleted — inbound legacy
references keep resolving via the cascade's opposite-collection fallback, and
typed reciprocal axons are rewritten here to the new collection. Synthesis
hubs are NEVER moved (they anchor Ariadne's Thread); misclassified hubs are
flagged in telemetry for manual decision. Immune engrams are never touched.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from qdrant_client import models

import red_pill.config as cfg
from red_pill.metabolism.distiller import classify_category
from red_pill.schemas import normalize_associations

logger = logging.getLogger(__name__)

REVIEWED_KEY = "category_reviewed_at"
WOULD_MOVE_KEY = "revision_would_move_to"
COLLECTIONS = ("work_memories", "social_memories")


def backlog_count(client) -> Dict[str, int]:
	"""Unreviewed engrams per collection — the upgrade/import advisory reads this."""
	counts = {}
	for col in COLLECTIONS:
		try:
			counts[col] = client.count(
				collection_name=col,
				count_filter=models.Filter(must_not=[models.FieldCondition(key=REVIEWED_KEY, range=models.Range(gt=0))]),
				exact=True,
			).count
		except Exception:
			counts[col] = -1
	return counts


def _opposite(collection: str) -> str:
	return "social_memories" if collection == "work_memories" else "work_memories"


def _rewire_reciprocal_axons(client, moved_id: str, payload: dict, old_col: str, new_col: str) -> int:
	"""Twins pointing at the moved engram still say target_collection=old_col —
	without this rewrite the weaver's repair pass would GC them as dangling."""
	rewired = 0
	for axon in normalize_associations(payload.get("associations", [])):
		if not axon.is_cross(old_col) or not axon.target_collection:
			continue
		try:
			twins = client.retrieve(collection_name=axon.target_collection, ids=[axon.id], with_payload=True, with_vectors=False)
			if not twins:
				continue
			twin_payload = twins[0].payload or {}
			twin_assocs = twin_payload.get("associations", [])
			changed = False
			for entry in twin_assocs:
				if isinstance(entry, dict) and str(entry.get("id")) == moved_id and entry.get("target_collection") == old_col:
					entry["target_collection"] = new_col
					changed = True
			if changed:
				client.set_payload(collection_name=axon.target_collection, payload={"associations": twin_assocs}, points=[axon.id])
				rewired += 1
		except Exception as e:
			logger.debug(f"[REVISION] reciprocal rewire failed for {axon.id}: {e}")
	return rewired


def revise_classifications(memory_manager, batch_size: Optional[int] = None, dry_run: Optional[bool] = None) -> Dict[str, Any]:
	client = memory_manager.client
	batch = batch_size if batch_size is not None else cfg.REVISION_BATCH_SIZE
	dry = dry_run if dry_run is not None else cfg.REVISION_DRY_RUN
	now = time.time()

	stats: Dict[str, Any] = {
		"reviewed": 0,
		"confirmed": 0,
		"would_move": 0,
		"moved": 0,
		"hubs_flagged": 0,
		"axons_rewired": 0,
		"llm_failures": 0,
		"dry_run": dry,
	}

	unreviewed_filter = models.Filter(
		must_not=[
			models.FieldCondition(key=REVIEWED_KEY, range=models.Range(gt=0)),
			models.FieldCondition(key="immune", match=models.MatchValue(value=True)),
			models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent")),
			models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="texture_shadow")),
			models.FieldCondition(key="_is_fragment", match=models.MatchValue(value=True)),
		]
	)

	# work_memories first: it is the inflated collection (R1 root cause).
	remaining = batch
	for collection in COLLECTIONS:
		if remaining <= 0:
			break
		points: List[Any] = []
		offset = None
		while len(points) < remaining:
			try:
				fetched, offset = client.scroll(
					collection_name=collection,
					scroll_filter=unreviewed_filter,
					limit=min(64, remaining - len(points)),
					with_payload=True,
					with_vectors=True,
					offset=offset,
				)
			except Exception as e:
				logger.error(f"[REVISION] scroll failed on {collection}: {e}")
				break
			points.extend(fetched)
			if offset is None:
				break

		for point in points:
			payload = point.payload or {}
			content = str(payload.get("content", ""))
			if not content:
				client.set_payload(collection_name=collection, payload={REVIEWED_KEY: now}, points=[point.id])
				continue

			verdict = classify_category(content)
			if verdict is None:
				stats["llm_failures"] += 1
				continue  # unmarked on purpose: a later cycle retries

			stats["reviewed"] += 1
			correct_col = f"{verdict}_memories"
			if correct_col == collection or correct_col not in COLLECTIONS:
				stats["confirmed"] += 1
				client.set_payload(collection_name=collection, payload={REVIEWED_KEY: now, "category": verdict}, points=[point.id])
				continue

			is_hub = payload.get("lazarus_phase") == "synthesis_hub" or payload.get("node_type") == "synthesis_hub"
			if is_hub:
				# Hubs anchor Ariadne's Thread: never moved automatically.
				stats["hubs_flagged"] += 1
				client.set_payload(
					collection_name=collection, payload={REVIEWED_KEY: now, WOULD_MOVE_KEY: correct_col, "hub_locked": True}, points=[point.id]
				)
				continue

			if dry:
				stats["would_move"] += 1
				client.set_payload(collection_name=collection, payload={REVIEWED_KEY: now, WOULD_MOVE_KEY: correct_col}, points=[point.id])
				continue

			# Execute the move: same ID, correct collection, then delete the original.
			try:
				new_payload = dict(payload)
				new_payload["category"] = verdict
				new_payload[REVIEWED_KEY] = now
				new_payload.pop(WOULD_MOVE_KEY, None)
				client.upsert(
					collection_name=correct_col,
					points=[models.PointStruct(id=point.id, vector=list(point.vector), payload=new_payload)],
				)
				stats["axons_rewired"] += _rewire_reciprocal_axons(client, str(point.id), payload, collection, correct_col)
				client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[point.id]))
				stats["moved"] += 1
			except Exception as e:
				logger.error(f"[REVISION] move failed for {collection}:{point.id}: {e}")

		remaining -= len(points)

	return stats


def drain(memory_manager, batch_size: int = 200, dry_run: bool = False, max_batches: int = 1000) -> Dict[str, Any]:
	"""Serial batches until the backlog is empty (post-validation, operator-launched)."""
	totals: Dict[str, Any] = {}
	for i in range(max_batches):
		stats = revise_classifications(memory_manager, batch_size=batch_size, dry_run=dry_run)
		for k, v in stats.items():
			if isinstance(v, (int, float)) and not isinstance(v, bool):
				totals[k] = totals.get(k, 0) + v
		processed = stats["reviewed"] + stats["llm_failures"]
		logger.info(f"[REVISION DRAIN] batch {i + 1}: {stats}")
		if processed == 0:
			break
	totals["dry_run"] = dry_run
	return totals
