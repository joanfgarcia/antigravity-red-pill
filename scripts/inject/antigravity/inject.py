"""Inject red-pill into Antigravity (Gemini).

Handles: anchor blocks (GEMINI.md), MCP config, skills symlinks.
Delegates to the legacy monolithic scripts with --ide antigravity.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

logger = logging.getLogger("inject_antigravity")

INJECT_ROOT = os.path.dirname(__file__)
SCRIPTS_ROOT = os.path.join(INJECT_ROOT, "..")


def inject(args: argparse.Namespace) -> int:
	redpill_dir = getattr(args, "redpill_dir", None) or os.path.join(INJECT_ROOT, "..", "..")
	redpill_dir = os.path.abspath(redpill_dir)
	uv = getattr(args, "uv_path", None) or "uv"
	changed = 0

	# Anchor blocks → GEMINI.md
	anchor_script = os.path.join(SCRIPTS_ROOT, "inject_anchor.py")
	if os.path.exists(anchor_script):
		cmd = [uv, "run", "python", anchor_script, "--ide", "antigravity", "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  antigravity anchors → {result.stdout.strip().split(chr(10))[-1]}")

	# MCP → mcp_config.json
	mcp_script = os.path.join(SCRIPTS_ROOT, "inject_mcp.py")
	if os.path.exists(mcp_script):
		uv_path = getattr(args, "uv_path", None) or "uv"
		cmd = [uv, "run", "python", mcp_script, "--uv-path", uv_path, "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  antigravity MCP → {result.stdout.strip().split(chr(10))[-1]}")

	return changed
