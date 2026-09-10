"""Detect pi-coding-agent presence for the injection registry.

Only gates on the Pi CLI or its agent dir existing. Pi auto-discovers
`~/.pi/agent/extensions/*.ts` and `~/.pi/agent/skills/`, so no config file
merge is needed (and Pi does not support MCP).
"""

from __future__ import annotations

import os
import shutil


def detect(workspace: str | None = None) -> bool:
	if shutil.which("pi"):
		return True
	return os.path.isdir(os.path.expanduser("~/.pi/agent"))
