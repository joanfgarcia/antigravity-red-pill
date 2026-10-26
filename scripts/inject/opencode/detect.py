"""Detect OpenCode installation and version.

`detect()` keeps the registry contract (bool). `info()` exposes the version
probe so the injector can pick the matching seed tier (V1 vs V2).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))
from opencode_version import detect_info  # noqa: E402


def detect(workspace: str | None = None) -> bool:
	return detect_info().installed


def info(workspace: str | None = None):
	"""Return the structured OpenCode detection (installed, version, major, source)."""
	config_path = os.path.expanduser("~/.config/opencode/opencode.jsonc")
	return detect_info(config_path=config_path)
