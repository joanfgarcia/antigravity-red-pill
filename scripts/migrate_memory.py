#!/usr/bin/env python3
"""
migrate_memory.py — Per-workspace memory relocation (.claude/memory → .red-pill/memory)

red-pill owns the agent's memory; per the workspace-neutral convention each project
workspace keeps its memory bank under `<root>/.red-pill/memory` (not `<root>/.claude/memory`,
which is IDE-specific). This migration moves ONLY the `memory/` directory — never `.claude/`
as a whole — for every registered project workspace.

IDEMPOTENT and SAFE to re-run:
- skips a workspace whose `.claude/memory` is absent (nothing to move / already migrated),
- skips (never overwrites) if `.red-pill/memory` already exists at the destination.

Hooked from scripts/upgrade.sh. Run manually to inspect:
	uv run python scripts/migrate_memory.py --dry-run
"""

import argparse
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_memory")


def migrate(dry_run: bool = False) -> int:
	sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
	from red_pill.core.workspaces import list_workspaces

	workspaces = list_workspaces()
	if not workspaces:
		logger.info("No project workspaces registered — nothing to migrate.")
		return 0

	migrated = skipped = errors = 0
	for ws in workspaces:
		old_mem = ws.root / ".claude" / "memory"
		new_mem = ws.root / ".red-pill" / "memory"

		if new_mem.exists():
			logger.info("✓ %s: %s already present — skip (idempotent).", ws.name, new_mem)
			skipped += 1
			continue
		if not old_mem.is_dir():
			logger.info("· %s: no %s — nothing to migrate.", ws.name, old_mem)
			skipped += 1
			continue

		try:
			if not dry_run:
				new_mem.parent.mkdir(parents=True, exist_ok=True)
				shutil.move(str(old_mem), str(new_mem))
			verb = "Would move" if dry_run else "Moved"
			logger.info("✓ %s: %s %s → .red-pill/memory", ws.name, verb, old_mem)
			migrated += 1
		except Exception as exc:
			logger.error("✗ %s: failed to migrate %s: %s", ws.name, old_mem, exc)
			errors += 1

	verb = "Would migrate" if dry_run else "Migrated"
	logger.info("%s %d workspace(s); skipped %d; errors %d.", verb, migrated, skipped, errors)
	return 1 if errors else 0


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Relocate per-workspace memory (.claude → .red-pill)")
	parser.add_argument("--dry-run", action="store_true", help="Show what would be done without moving anything")
	args = parser.parse_args()
	sys.exit(migrate(dry_run=args.dry_run))
