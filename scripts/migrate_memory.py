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
import json
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_memory")


def _deep_str_replace(obj, old: str, new: str):
	"""Recursively replace the substring `old` with `new` in every string leaf of
	a JSON-like structure. Returns (new_obj, n_changes)."""
	if isinstance(obj, str):
		if old in obj:
			return obj.replace(old, new), obj.count(old)
		return obj, 0
	if isinstance(obj, list):
		out, n = [], 0
		for item in obj:
			v, c = _deep_str_replace(item, old, new)
			out.append(v)
			n += c
		return out, n
	if isinstance(obj, dict):
		out, n = {}, 0
		for k, v in obj.items():
			nv, c = _deep_str_replace(v, old, new)
			out[k] = nv
			n += c
		return out, n
	return obj, 0


def _repoint_mcp_configs(workspace_root, old_path: str, new_path: str, dry_run: bool) -> int:
	"""After moving a workspace's memory, rewrite any MCP config entry that still
	references the old absolute path → the new one. Generic and MCP-name-agnostic:
	matches by path string, so it fixes the filesystem server, the agent-bridge's
	MEMORY_FILE_PATH/KNOWLEDGE_GRAPH_PATH, etc. Reuses inject_mcp's target list so
	the move stays coordinated with the serving config without manual --update."""
	sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
	from inject_mcp import discover_targets

	repointed = 0
	for cfg in discover_targets(str(workspace_root)):
		if not os.path.exists(cfg):
			continue
		try:
			with open(cfg, "r", encoding="utf-8") as f:
				data = json.load(f)
		except Exception as exc:
			logger.warning("  ↳ skip unreadable config %s: %s", cfg, exc)
			continue
		new_data, n = _deep_str_replace(data, old_path, new_path)
		if not n:
			continue
		verb = "Would re-point" if dry_run else "Re-pointed"
		logger.info("  ↳ %s %d MCP ref(s) in %s", verb, n, cfg)
		repointed += 1
		if not dry_run:
			shutil.copy2(cfg, cfg + ".bak")
			with open(cfg, "w", encoding="utf-8") as f:
				json.dump(new_data, f, indent=2, ensure_ascii=False)
				f.write("\n")
	return repointed


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
			# Coordinate the serving config with the move: re-point any MCP entry
			# that referenced the old path so no manual --update is needed.
			_repoint_mcp_configs(ws.root, str(old_mem), str(new_mem), dry_run)
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
