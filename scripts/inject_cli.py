#!/usr/bin/env python3
"""Generic IDE injection dispatcher.

Scans scripts/inject/<ide>/ for detect.py + inject.py adapters and runs
them.  This is the SINGLE entry-point called by install_neo.sh and
upgrade.sh — those scripts never need to be modified when adding a new IDE.

Usage:
	python scripts/inject_cli.py --redpill-dir /path/to/red-pill [--uv-path /path/to/uv]
	python scripts/inject_cli.py --list                    # show discovered adapters
	python scripts/inject_cli.py --ide opencode --remove   # remove red-pill from one IDE
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("inject_cli")

# Ensure the inject package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inject._registry import detect_present, discover_adapters, inject_all  # noqa: E402


def main():
	parser = argparse.ArgumentParser(description="Red Pill IDE injection dispatcher.")
	parser.add_argument("--redpill-dir", help="Path to Red Pill source directory.")
	parser.add_argument("--uv-path", help="Path to uv binary.")
	parser.add_argument("--workspace", help="Workspace root (for project-scoped configs).")
	parser.add_argument("--update", action="store_true", help="Force-update anchor blocks.")
	parser.add_argument("--no-backup", action="store_true", help="Skip .bak backups.")
	parser.add_argument("--remove", action="store_true", help="Remove red-pill from target IDE(s).")
	parser.add_argument("--list", action="store_true", help="List discovered adapters and exit.")
	parser.add_argument("--ide", help="Target a specific IDE (csv). Default: auto-detect all present.")
	args = parser.parse_args()

	adapters = discover_adapters()

	if args.list:
		print("Discovered IDE adapters:")
		for a in adapters:
			present = a.detect_mod.detect(args.workspace)
			status = "PRESENT" if present else "absent"
			print(f"  {a.name:20s} [{status}]")
		return

	if args.ide:
		target_names = [n.strip() for n in args.ide.split(",")]
		adapters = [a for a in adapters if a.name in target_names]
		if not adapters:
			logger.error(f"No adapter found for: {args.ide}")
			sys.exit(1)
	else:
		adapters = detect_present(args.workspace)

	if not adapters:
		logger.info("No present IDEs detected. Nothing to inject.")
		return

	logger.info(f"Targeting: {', '.join(a.name for a in adapters)}")
	total = inject_all(args, adapters)
	logger.info(f"Done. {total} block(s) modified across {len(adapters)} IDE(s).")


if __name__ == "__main__":
	main()
