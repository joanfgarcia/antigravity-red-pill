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


def precheck(workspace: str | None = None) -> tuple[bool, str]:
	"""Hard gate: Red Pill now requires OpenCode v2."""
	inf = info(workspace)
	if not inf.installed:
		return True, ""
	if (inf.major or 0) < 2:
		return False, (
			f"OpenCode {inf} detectado. Red Pill ya NO es compatible con OpenCode v1. "
			"Actualiza a v2: curl -fsSL https://opencode.ai/v2/install | bash"
		)
	return True, ""
