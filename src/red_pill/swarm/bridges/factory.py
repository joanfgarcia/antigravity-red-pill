"""
AgentBridge Factory — Creates the appropriate bridge based on config or an
explicit backend.

	- create_bridge(backend=None): prompt EXECUTION (Telegram, AWAKENINGs, AgentMinion)
	- create_extraction_bridge(): conversation EXTRACTION (Chronicle, GrpcBridge)
	- preflight_check(): validate the agy/IDE environment before autonomous ops

Antigravity-specific backends (agy, grpc) live in plugins/antigravity_ide and are
imported lazily; claude/local live alongside this factory.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, Dict, Optional

import red_pill.config as cfg

from .base import AgentBridge

logger = logging.getLogger(__name__)


def create_bridge(backend: Optional[str] = None) -> AgentBridge:
	"""Create an execution bridge.

	Routes on `backend` (explicit) or `IDE_BACKEND` config:
		- "agy"    : AgyBridge (requires agy CLI)            [antigravity_ide]
		- "claude" : ClaudeBridge (requires claude CLI)
		- "local"  : LocalBridge (local model via SIP provider)
		- "grpc"   : GrpcBridge (legacy extraction backend)  [antigravity_ide]
		- "auto"   : agy if available, else grpc

	For conversation extraction (Chronicle), use create_extraction_bridge().
	"""
	backend = (backend or cfg.get_config().IDE_BACKEND or "auto").strip().lower()

	if backend == "auto":
		backend = "agy" if shutil.which("agy") else "grpc"

	if backend == "agy":
		from red_pill.plugins.antigravity_ide.agy_bridge import AgyBridge

		return AgyBridge()
	if backend == "claude":
		from .claude import ClaudeBridge

		return ClaudeBridge()
	if backend == "local":
		from .local import LocalBridge

		return LocalBridge()

	from red_pill.plugins.antigravity_ide.grpc_bridge import GrpcBridge

	return GrpcBridge()


def create_extraction_bridge() -> AgentBridge:
	"""Create the extraction bridge for the Chronicle pipeline.

	Always returns GrpcBridge — the only backend that can read conversation
	trajectories from the LanguageServer.
	"""
	from red_pill.plugins.antigravity_ide.grpc_bridge import GrpcBridge

	return GrpcBridge()


def preflight_check() -> Dict[str, Any]:
	"""Validate the agy/IDE environment for Neon-Link/autonomous features.

	Returns dict with: ready (bool), backend (str), agy_version (str|None),
	warnings (list), errors (list). Called by the worker before processing the inbox.
	"""
	result: Dict[str, Any] = {
		"ready": False,
		"backend": "none",
		"agy_version": None,
		"warnings": [],
		"errors": [],
	}

	agy_path = shutil.which("agy")
	if agy_path:
		result["backend"] = "agy"
		result["ready"] = True
		try:
			import subprocess

			ver = subprocess.run([agy_path, "--version"], capture_output=True, text=True, timeout=5)
			result["agy_version"] = ver.stdout.strip()
		except Exception:
			result["agy_version"] = "unknown"
	else:
		result["backend"] = "grpc"
		result["errors"].append(
			"Antigravity CLI (agy) not found. "
			"Neon-Link command execution and autonomous awakenings require agy >= 1.0. "
			"Install: curl -fsSL https://antigravity.google/cli/install.sh | bash"
		)
		result["warnings"].append("Falling back to gRPC backend (v1). Auto-approval and ephemeral mode are NOT available.")

	try:
		from red_pill.utils.antigravity_history.discovery import discover_language_servers

		servers = discover_language_servers()
		if not servers:
			result["warnings"].append("No Antigravity IDE session detected. Bridge may fail at runtime.")
	except Exception as e:
		result["warnings"].append(f"IDE discovery failed: {e}")

	return result
