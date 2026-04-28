#!/usr/bin/env python3
"""
thread_weave_migrate.py — Retroactive Thread Weaving Migration

Chains all existing synthesis_hub nodes in work_memories and social_memories
with bidirectional temporal axons (prev_session_hub / next_session_hub),
sorted by created_at.

This is an IDEMPOTENT migration — safe to re-run. Existing axons are
overwritten with the correct values.

Also bootstraps ~/.agent/thread_state.json so the next sleep cycle
continues the thread from the most recent hub.

Run once after upgrading to sleep.py Phase 5 (Thread Weaving):
	uv run python scripts/thread_weave_migrate.py

Run with --dry-run to inspect without writing:
	uv run python scripts/thread_weave_migrate.py --dry-run
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("thread_weave_migrate")

THREAD_STATE_PATH = os.path.expanduser("~/.agent/thread_state.json")
COLLECTIONS = ["archive_memories", "work_memories", "social_memories", "directive_memories"]


def migrate(dry_run: bool = False) -> None:
	sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
	from red_pill.memory import MemoryManager

	mem = MemoryManager()
	client = mem.client
	thread_state: dict = {}

	for col in COLLECTIONS:
		logger.info(f"=== {col} ===")

		try:
			all_pts = client.scroll(col, limit=10000, with_payload=True)[0]
		except Exception as e:
			logger.warning(f"Could not load {col}: {e}")
			continue

		# Collection-specific hub selection
		if col == "archive_memories":
			# Chain chronicle and monolith nodes in temporal sequence
			hubs = [p for p in all_pts if p.payload.get("type", "") in ("chronicle_node", "monolith_parent")]
		elif col == "directive_memories":
			# Directives are all woven indiscriminately
			hubs = list(all_pts)
		else:
			# work_memories / social_memories: synthesis hubs only
			hubs = [p for p in all_pts if p.payload.get("lazarus_phase") == "synthesis_hub"]

		if not hubs:
			logger.info("  No synthesis_hub nodes found — skipping.")
			continue

		# Sort chronologically by created_at
		hubs.sort(key=lambda p: p.payload.get("created_at", 0))
		logger.info(f"  Found {len(hubs)} hubs spanning {hubs[0].payload.get('created_at', '?')} → {hubs[-1].payload.get('created_at', '?')}")

		linked = 0
		for i in range(1, len(hubs)):
			prev = hubs[i - 1]
			curr = hubs[i]
			try:
				if not dry_run:
					client.set_payload(col, payload={"prev_session_hub": str(prev.id)}, points=[curr.id])
					client.set_payload(col, payload={"next_session_hub": str(curr.id)}, points=[prev.id])
				linked += 1
			except Exception as e:
				logger.error(f"  ERROR linking {prev.id} → {curr.id}: {e}")

		action = "Would link" if dry_run else "Linked"
		logger.info(f"  {action} {linked}/{len(hubs) - 1} hub pairs OK")

		# Bootstrap: point to the most recent hub
		thread_state[col] = str(hubs[-1].id)

	# Save thread_state.json
	if not dry_run:
		os.makedirs(os.path.dirname(THREAD_STATE_PATH), exist_ok=True)
		with open(THREAD_STATE_PATH, "w") as f:
			json.dump(thread_state, f, indent=2)
		logger.info(f"thread_state.json bootstrapped: {thread_state}")
	else:
		logger.info(f"[DRY RUN] Would write thread_state.json: {thread_state}")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Retroactive Thread Weaving Migration")
	parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
	args = parser.parse_args()
	migrate(dry_run=args.dry_run)
