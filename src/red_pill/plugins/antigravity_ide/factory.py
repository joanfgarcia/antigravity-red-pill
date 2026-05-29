"""
IDEBridge Factory — Creates the appropriate bridge based on config.

Two factories:
	- create_bridge(): For prompt EXECUTION (Telegram, AWAKENINGs)
	- create_extraction_bridge(): For conversation EXTRACTION (Chronicle)

Also provides preflight_check() for validating the environment
before processing Neon-Link commands or autonomous tasks.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

import red_pill.config as cfg

from .bridge import IDEBridge

logger = logging.getLogger(__name__)


def create_bridge() -> IDEBridge:
	"""Create the execution bridge based on config.

	Routes based on IDE_BACKEND setting in .env:
		- "agy": Force AgyBridge (requires agy CLI)
		- "grpc": Force GrpcBridge (legacy)
		- "auto": Auto-detect (agy if available, else grpc)

	For conversation extraction (Chronicle), use create_extraction_bridge().
	"""
	backend = cfg.get_config().IDE_BACKEND

	if backend == "auto":
		backend = "agy" if shutil.which("agy") else "grpc"

	if backend == "agy":
		from .agy_bridge import AgyBridge

		return AgyBridge()
	else:
		from .grpc_bridge import GrpcBridge

		return GrpcBridge()


def create_extraction_bridge() -> IDEBridge:
	"""Create the extraction bridge for Chronicle pipeline.

	Always returns GrpcBridge — it's the only backend that can
	read conversation trajectories from the LanguageServer.
	"""
	from .grpc_bridge import GrpcBridge

	return GrpcBridge()


def preflight_check() -> Dict[str, Any]:
	"""Validate environment for Neon-Link/autonomous features.

	Returns dict with:
		- ready (bool): True if the backend can execute prompts autonomously
		- backend (str): Resolved backend name ("agy" or "grpc")
		- agy_version (str|None): Version string if agy is installed
		- warnings (list[str]): Non-fatal issues
		- errors (list[str]): Fatal issues preventing autonomous operation

	Called by worker before processing inbox. If ready=False and the
	message requires auto-approve (AWAKENING, autonomous), it should
	be skipped with a clear log warning.
	"""
	result: Dict[str, Any] = {
		"ready": False,
		"backend": "none",
		"agy_version": None,
		"warnings": [],
		"errors": [],
	}

	# Check for agy CLI
	agy_path = shutil.which("agy")
	if agy_path:
		result["backend"] = "agy"
		result["ready"] = True
		# Try to get version
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

	# Check IDE connectivity
	try:
		from red_pill.utils.antigravity_history.discovery import discover_language_servers

		servers = discover_language_servers()
		if not servers:
			result["warnings"].append("No Antigravity IDE session detected. Bridge may fail at runtime.")
	except Exception as e:
		result["warnings"].append(f"IDE discovery failed: {e}")

	return result
