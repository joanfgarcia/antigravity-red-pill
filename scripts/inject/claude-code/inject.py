"""Inject red-pill into Claude Code.

Handles: anchor blocks (CLAUDE.md), MCP config, settings.json.
Delegates to the legacy monolithic scripts.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess

logger = logging.getLogger("inject_claude_code")

INJECT_ROOT = os.path.dirname(__file__)
SCRIPTS_ROOT = os.path.join(INJECT_ROOT, "..")


def inject(args: argparse.Namespace) -> int:
	redpill_dir = getattr(args, "redpill_dir", None) or os.path.join(INJECT_ROOT, "..", "..")
	redpill_dir = os.path.abspath(redpill_dir)
	uv = getattr(args, "uv_path", None) or "uv"
	changed = 0

	# Anchor blocks → CLAUDE.md
	anchor_script = os.path.join(SCRIPTS_ROOT, "inject_anchor.py")
	if os.path.exists(anchor_script):
		cmd = [uv, "run", "python", anchor_script, "--ide", "claude-code", "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  claude-code anchors → {result.stdout.strip().split(chr(10))[-1]}")

	# MCP → .claude.json
	mcp_script = os.path.join(SCRIPTS_ROOT, "inject_mcp.py")
	if os.path.exists(mcp_script):
		uv_path = getattr(args, "uv_path", None) or "uv"
		cmd = [uv, "run", "python", mcp_script, "--uv-path", uv_path, "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  claude-code MCP → {result.stdout.strip().split(chr(10))[-1]}")

	# Settings → settings.json
	settings_script = os.path.join(SCRIPTS_ROOT, "inject_settings.py")
	if os.path.exists(settings_script):
		cmd = [uv, "run", "python", settings_script, "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  claude-code settings → {result.stdout.strip().split(chr(10))[-1]}")

	return changed
