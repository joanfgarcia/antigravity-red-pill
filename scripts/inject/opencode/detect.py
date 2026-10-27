"""Detect OpenCode installation and version.

`detect()` keeps the registry contract (bool). `info()` exposes the version probe
and `precheck()` the hard gate: red-pill only seeds OpenCode v2, and an
undetectable version aborts instead of defaulting to a tier.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))
from opencode_version import detect_info, support_error  # noqa: E402


def detect(workspace: str | None = None) -> bool:
	return detect_info().installed


def info(workspace: str | None = None):
	"""Return the structured OpenCode detection (installed, version, major, source)."""
	return detect_info()


def precheck(workspace: str | None = None) -> tuple[bool, str]:
	"""Hard gate: red-pill requires OpenCode v2, with a known version.

	Not installed → pass (there is nothing to seed). Installed → the version must
	be established and be exactly v2; v1 (migration only), a future v3, a
	CLI/dpkg disagreement or an undetectable version all abort with a message.
	"""
	inf = info(workspace)
	problem = support_error(inf)
	if problem:
		return False, problem
	return True, ""
