#!/usr/bin/env python3
"""Render the active GIT_WORKFLOW profile into the agent rule (installer helper)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from red_pill.core.git_workflow import write_git_workflow  # noqa: E402


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--profile", default="solo")
	parser.add_argument("--source", default=str(REPO / "seeds" / "rules" / "git_workflow.md"))
	parser.add_argument("--output", required=True)
	args = parser.parse_args()
	try:
		write_git_workflow(args.profile, Path(args.source), Path(args.output))
	except Exception as e:
		print(f"[git-workflow] error: {e}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
