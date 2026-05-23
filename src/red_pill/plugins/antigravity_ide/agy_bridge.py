"""
AgyBridge — Execution backend using agy CLI (Antigravity >= 2.0)

Uses `agy -p --dangerously-skip-permissions` for headless, auto-approved
prompt execution. No API key needed — uses ANTIGRAVITY_LS_ADDRESS +
ANTIGRAVITY_CSRF_TOKEN from the local IDE session.

Requirements:
    - agy CLI installed (>= 1.0)
    - Antigravity IDE running (language_server process active)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Optional, Tuple

from .bridge import BackendType, BridgeCapabilities, ConversationResult, IDEBridge

logger = logging.getLogger(__name__)


class AgyBridge(IDEBridge):
	"""Backend v2: agy CLI with --dangerously-skip-permissions.

	Supports:
		- One-shot prompts (ephemeral, no ghost cascades)
		- Conversation resume (-c flag)
		- Auto-approval of all tool calls
		- MCP tool usage within the agent
	"""

	AGY_BIN = "agy"

	def __init__(self, agy_path: Optional[str] = None):
		self._agy_path = agy_path or shutil.which(self.AGY_BIN)
		if not self._agy_path:
			raise RuntimeError(
				"Antigravity CLI (agy) not found in PATH. "
				"Neon-Link command execution and autonomous AWAKENINGs require agy >= 1.0. "
				"Install: curl -fsSL https://antigravity.google/cli/install.sh | bash"
			)

	def _get_env(self) -> dict:
		"""Build env dict with LS_ADDRESS and CSRF_TOKEN.

		If running inside the IDE, these are already set as env vars.
		If running externally (systemd timer, cron), discover from running processes.
		"""
		env = os.environ.copy()
		if "ANTIGRAVITY_LS_ADDRESS" not in env:
			try:
				addr, token = self._discover_ls()
				env["ANTIGRAVITY_LS_ADDRESS"] = addr
				env["ANTIGRAVITY_CSRF_TOKEN"] = token
			except Exception as e:
				logger.error(f"Failed to discover LanguageServer: {e}")
				raise RuntimeError(
					"Cannot discover Antigravity IDE session. "
					"Ensure the IDE is running or set ANTIGRAVITY_LS_ADDRESS and ANTIGRAVITY_CSRF_TOKEN."
				) from e
		return env

	def _discover_ls(self) -> Tuple[str, str]:
		"""Discover language_server address and CSRF token from running processes."""
		from red_pill.utils.antigravity_history.discovery import discover_language_servers, find_all_endpoints

		servers = discover_language_servers()
		if not servers:
			raise RuntimeError("No Antigravity IDE LanguageServers found.")
		endpoints = find_all_endpoints(servers)
		if not endpoints:
			raise RuntimeError("No valid IDE endpoints discovered.")
		ep = endpoints[0]
		return f"localhost:{ep['port']}", ep["csrf"]

	def _run_agy(self, args: list, timeout: int) -> str:
		"""Execute agy CLI with common flags."""
		cmd = [
			self._agy_path,
			*args,
			"--dangerously-skip-permissions",
			"--print-timeout",
			f"{timeout}s",
		]
		logger.debug(f"[AgyBridge] Running: {' '.join(cmd[:4])}... (timeout={timeout}s)")
		try:
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=timeout + 10,
				env=self._get_env(),
				cwd=os.path.expanduser("~/Documents/IA"),
			)
		except subprocess.TimeoutExpired as e:
			logger.error(f"[AgyBridge] Command timed out after {timeout + 10}s")
			raise RuntimeError(f"agy timed out after {timeout}s") from e

		if result.returncode != 0:
			stderr = result.stderr.strip()
			logger.error(f"[AgyBridge] agy failed (rc={result.returncode}): {stderr}")
			raise RuntimeError(f"agy failed (rc={result.returncode}): {stderr}")

		return result.stdout.strip()

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.AGY,
			auto_approve=True,
			ephemeral_mode=True,
			conversation_resume=True,
			model_selection=True,
			mcp_tools=True,
		)

	def prompt(self, text: str, *, model: str = "flash", timeout: int = 120) -> ConversationResult:
		"""Send a one-shot prompt via agy -p."""
		try:
			response = self._run_agy(["-p", text], timeout)
			return ConversationResult(
				conversation_id="ephemeral",
				response=response,
				model=model,
			)
		except Exception as e:
			return ConversationResult(
				conversation_id="ephemeral",
				response="",
				error=str(e),
			)

	def continue_conversation(self, text: str, *, timeout: int = 120) -> ConversationResult:
		"""Continue the most recent agy conversation via agy -c -p."""
		try:
			response = self._run_agy(["-c", "-p", text], timeout)
			return ConversationResult(
				conversation_id="continued",
				response=response,
			)
		except Exception as e:
			return ConversationResult(
				conversation_id="continued",
				response="",
				error=str(e),
			)

	def health_check(self) -> bool:
		"""Quick connectivity test — sends a minimal prompt."""
		try:
			result = self.prompt("Responde SOLO: OK", timeout=30)
			return result.ok and "OK" in result.response
		except Exception:
			return False
