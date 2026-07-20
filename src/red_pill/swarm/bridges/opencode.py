"""
OpenCodeBridge — Execution backend using the OpenCode CLI (`opencode`).

Uses `opencode run --format json --auto` for headless, auto-approved prompt
execution.  The JSON output is a stream of events; we extract the session ID
from step_start events and the response text from text events.

When a persistent OpenCode server is available (via `opencode serve` or the
TUI), set OPENCODE_SERVER_URL (e.g. http://localhost:4096) to reuse its MCP
connections and avoid cold-start on every call.

Requirements:
- opencode CLI installed and configured (~/.config/opencode/).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Optional

from red_pill.core.paths import get_bunker_root

from .base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

logger = logging.getLogger(__name__)

OPENCODE_BIN = "opencode"


class OpenCodeBridge(AgentBridge):
	"""Execution backend: OpenCode CLI, headless + auto-approved.

	Mirrors ClaudeBridge, but uses ``opencode run --format json --auto`` and
	parses the streaming JSON event format to extract session_id and response.

	Two execution modes:

	1. **Direct** (default): ``opencode run`` — cold start, MCP servers initialize
	   per call.  Zero dependencies beyond the opencode CLI.

	2. **Attached**: ``opencode run --attach <url>`` — reuses a persistent
	   ``opencode serve`` instance, avoiding MCP cold-start.  Set
	   ``OPENCODE_SERVER_URL`` env var or pass ``server_url`` to the constructor.

	Requirements:
	- opencode CLI installed and configured (~/.config/opencode/).
	"""

	def __init__(self, opencode_path: Optional[str] = None, server_url: Optional[str] = None):
		self._opencode_path = opencode_path or shutil.which(OPENCODE_BIN)
		if not self._opencode_path:
			raise RuntimeError(
				"OpenCode CLI (opencode) not found in PATH. "
				"Install OpenCode and ensure `opencode` is available."
			)
		# Priority: explicit param > env var > config
		if server_url:
			self._server_url = server_url
		else:
			self._server_url = os.environ.get("OPENCODE_SERVER_URL", "")

	def _run_opencode(self, args: list, timeout: int, cwd: Optional[str] = None) -> dict:
		"""Execute opencode CLI with common flags and parse the streaming JSON output.

		Returns a dict with ``session_id`` and ``text`` (concatenated response).
		"""
		cmd = [self._opencode_path, "run", *args, "--format", "json", "--auto"]

		if self._server_url:
			cmd.extend(["--attach", self._server_url])

		logger.debug(
			f"[OpenCodeBridge] Running: {' '.join(cmd[:4])}... "
			f"(timeout={timeout}s, cwd={cwd or 'default'}, "
			f"server={'attached' if self._server_url else 'direct'})"
		)

		try:
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=timeout + 10,
				cwd=cwd or str(get_bunker_root().parent),
			)
		except subprocess.TimeoutExpired as e:
			logger.error(f"[OpenCodeBridge] Command timed out after {timeout + 10}s")
			raise RuntimeError(f"opencode timed out after {timeout}s") from e

		if result.returncode != 0:
			stderr = (result.stderr or "").strip()
			logger.error(f"[OpenCodeBridge] opencode failed (rc={result.returncode}): {stderr[:500]}")
			raise RuntimeError(f"opencode failed (rc={result.returncode}): {stderr[:300]}")

		return self._parse_json_stream(result.stdout or "")

	@staticmethod
	def _parse_json_stream(stdout: str) -> dict:
		"""Parse opencode's streaming JSON event format.

		Extracts:
		- ``session_id`` from the first ``step_start`` event.
		- ``text`` from all ``text`` events (concatenated).
		"""
		session_id = ""
		texts: list[str] = []

		for line in stdout.strip().splitlines():
			line = line.strip()
			if not line:
				continue
			try:
				event = json.loads(line)
			except json.JSONDecodeError:
				continue

			event_type = event.get("type", "")

			if event_type == "step_start" and not session_id:
				session_id = event.get("sessionID", "")

			elif event_type == "text":
				part = event.get("part", {})
				text = part.get("text", "")
				if text:
					texts.append(text)

		return {"session_id": session_id, "text": "".join(texts)}

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.OPENCODE,
			auto_approve=True,
			ephemeral_mode=True,
			conversation_resume=True,
			model_selection=True,
			mcp_tools=True,
		)

	def _model_args(self, model: str) -> list:
		if not model or model == "flash":
			return []
		# OpenCode uses -m provider/model format.
		# If model already contains a slash, use as-is; otherwise try anthropic/ prefix.
		if "/" in model:
			return ["-m", model]
		return ["-m", f"anthropic/{model}"]

	# Map the portable standard (low|medium|high) → opencode's --variant.
	# None/unknown → omit (model default).
	_EFFORT_MAP = {
		"low": "minimal",
		"high": "high",
		# "medium" → omit (opencode default is reasonable for medium)
	}

	@classmethod
	def _effort_args(cls, effort: Optional[str]) -> list:
		mapped = cls._EFFORT_MAP.get((effort or "").strip().lower())
		return ["--variant", mapped] if mapped else []

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		"""Send a one-shot prompt via ``opencode run``."""
		try:
			data = self._run_opencode(
				[text, *self._model_args(model), *self._effort_args(effort)],
				timeout,
				cwd=cwd,
			)
		except Exception as e:
			return ConversationResult(conversation_id="", response="", error=str(e))

		response = data.get("text", "")
		session_id = data.get("session_id", "")

		if not response:
			return ConversationResult(
				conversation_id=session_id,
				response="",
				error="opencode returned empty text response",
			)

		logger.info(f"[OpenCodeBridge] prompt() → session={session_id}, response_len={len(response)}")
		return ConversationResult(conversation_id=session_id, response=response, model=model)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		"""Continue a session via ``opencode run -s <id>``."""
		if not conversation_id:
			logger.warning("[OpenCodeBridge] continue_conversation without conversation_id → prompt()")
			return self.prompt(text, timeout=timeout)

		try:
			data = self._run_opencode(
				["-s", conversation_id, text],
				timeout,
			)
		except Exception as e:
			return ConversationResult(conversation_id=conversation_id, response="", error=str(e))

		return ConversationResult(
			conversation_id=data.get("session_id", conversation_id),
			response=data.get("text", ""),
		)

	def health_check(self) -> bool:
		"""Quick connectivity test — sends a minimal prompt."""
		try:
			result = self.prompt("Responde SOLO: OK", timeout=30)
			return result.ok and "OK" in result.response
		except Exception:
			return False
