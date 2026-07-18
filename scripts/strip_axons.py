"""Total rollback for ADR-AXON-001 payload additions (safety net, audit item 9).

Removes cross-collection axons from `associations` (local links preserved) and
deletes the fields introduced by the 7.7.0 line: texture, lang, relics,
emotional_vector, category_reviewed_at, revision_would_move_to, hub_locked.

Usage:
	uv run python scripts/strip_axons.py            # dry-run: report only
	uv run python scripts/strip_axons.py --execute  # apply
"""

import argparse
import sys

sys.path.insert(0, "src")

from red_pill.memory import MemoryManager  # noqa: E402
from red_pill.schemas import normalize_associations  # noqa: E402

STRIP_KEYS = ["texture", "lang", "relics", "emotional_vector", "category_reviewed_at", "revision_would_move_to", "hub_locked"]
COLLECTIONS = ["work_memories", "social_memories"]


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry-run report)")
	args = parser.parse_args()

	mm = MemoryManager()
	client = mm.client
	touched = {"axons_stripped": 0, "points_cleaned": 0, "shadows_deleted": 0}

	# T5 rollback: texture_shadow points are whole points, not fields — delete them.
	from qdrant_client import models

	for collection in COLLECTIONS:
		try:
			shadow_count = client.count(
				collection_name=collection,
				count_filter=models.Filter(must=[models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="texture_shadow"))]),
				exact=True,
			).count
			touched["shadows_deleted"] += shadow_count
			if args.execute and shadow_count:
				client.delete(
					collection_name=collection,
					points_selector=models.FilterSelector(
						filter=models.Filter(must=[models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="texture_shadow"))])
					),
				)
		except Exception:
			pass

	for collection in COLLECTIONS:
		offset = None
		while True:
			batch, offset = client.scroll(collection_name=collection, limit=128, with_payload=True, with_vectors=False, offset=offset)
			for point in batch:
				payload = point.payload or {}
				assocs = payload.get("associations", [])
				local_only = [
					entry
					for entry in (assocs if isinstance(assocs, list) else [])
					if not (normalize_associations([entry]) and normalize_associations([entry])[0].is_cross(collection))
				]
				stripped = len(assocs) - len(local_only) if isinstance(assocs, list) else 0
				has_new_fields = any(k in payload for k in STRIP_KEYS)
				if not stripped and not has_new_fields:
					continue
				touched["axons_stripped"] += stripped
				touched["points_cleaned"] += 1
				if args.execute:
					if stripped:
						client.set_payload(collection_name=collection, payload={"associations": local_only}, points=[point.id])
					present = [k for k in STRIP_KEYS if k in payload]
					if present:
						client.delete_payload(collection_name=collection, keys=present, points=[point.id])
			if offset is None:
				break

	mode = "EXECUTED" if args.execute else "DRY-RUN"
	print(
		f"[{mode}] points_cleaned={touched['points_cleaned']} cross_axons_stripped={touched['axons_stripped']} shadows_deleted={touched['shadows_deleted']}"
	)
	if not args.execute:
		print("Re-run with --execute to apply.")


if __name__ == "__main__":
	main()
