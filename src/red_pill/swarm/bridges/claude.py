"""
ClaudeBridge — Execution backend using the Claude Code CLI (`claude`).

Uses `claude -p --dangerously-skip-permissions --output-format json` for headless,
auto-approved prompt execution. The JSON output yields the result text and a
session_id, so multi-turn resume (`claude --resume <id>`) needs no dir-diff or
prefix-stripping (unlike AgyBridge).

Requirements:
- claude CLI installed and authenticated.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Optional

from red_pill.core.paths import get_bunker_root

from .base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

logger = logging.getLogger(__name__)


class ClaudeBridge(AgentBridge):
	"""Execution backend: Claude Code CLI, headless + auto-approved.

	Mirrors AgyBridge, but uses `--output-format json` to read the session_id and
	result directly (no brain dir-diff / prefix-strip needed).
	"""

	CLAUDE_BIN = "claude"

	def __init__(self, claude_path: Optional[str] = None):
		self._claude_path = claude_path or shutil.which(self.CLAUDE_BIN)
		if not self._claude_path:
			raise RuntimeError("Claude CLI (claude) not found in PATH. Install Claude Code and ensure `claude` is available.")

	def _run_claude(self, args: list, timeout: int, cwd: Optional[str] = None) -> dict:
		"""Execute claude CLI with common flags and parse the JSON result object.

		cwd: working dir for the subprocess (the target project). None → red-pill's
		own root (back-compat default for Telegram/AWAKENINGs callers).
		"""
		cmd = [self._claude_path, *args, "--dangerously-skip-permissions", "--output-format", "json"]
		logger.debug(f"[ClaudeBridge] Running: {' '.join(cmd[:3])}... (timeout={timeout}s, cwd={cwd or 'default'})")
		try:
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=timeout + 10,
				cwd=cwd or str(get_bunker_root().parent),
			)
		except subprocess.TimeoutExpired as e:
			logger.error(f"[ClaudeBridge] Command timed out after {timeout + 10}s")
			raise RuntimeError(f"claude timed out after {timeout}s") from e

		if result.returncode != 0:
			stderr = (result.stderr or "").strip()
			logger.error(f"[ClaudeBridge] claude failed (rc={result.returncode}): {stderr[:500]}")
			raise RuntimeError(f"claude failed (rc={result.returncode}): {stderr[:300]}")

		out = (result.stdout or "").strip()
		if not out:
			raise RuntimeError("claude returned empty output")
		try:
			return json.loads(out)
		except json.JSONDecodeError as e:
			raise RuntimeError(f"claude output was not JSON: {out[:200]}") from e

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.CLAUDE,
			auto_approve=True,
			ephemeral_mode=True,
			conversation_resume=True,
			model_selection=True,
			mcp_tools=True,
		)

	def _model_args(self, model: str) -> list:
		# The interface default ("flash") is agy-centric; ignore it for claude.
		return ["--model", model] if model and model != "flash" else []

	# Map the portable standard (low|medium|high) → claude's --effort. Claude also
	# accepts xhigh/max, but the portable standard tops at high. None/unknown → omit
	# (model default). This is the ClaudeBridge's slice of the standard→real mapping.
	_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high"}

	@classmethod
	def _effort_args(cls, effort: Optional[str]) -> list:
		mapped = cls._EFFORT_MAP.get((effort or "").strip().lower())
		return ["--effort", mapped] if mapped else []

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		"""Send a one-shot prompt via `claude -p`. session_id comes from the JSON output."""
		try:
			data = self._run_claude(["-p", text, *self._model_args(model), *self._effort_args(effort)], timeout, cwd=cwd)
		except Exception as e:
			return ConversationResult(conversation_id="", response="", error=str(e))

		if data.get("is_error"):
			return ConversationResult(
				conversation_id=data.get("session_id", ""),
				response="",
				error=str(data.get("result") or "claude reported is_error"),
			)
		conv = data.get("session_id", "")
		response = str(data.get("result", ""))
		logger.info(f"[ClaudeBridge] prompt() → conv={conv}, response_len={len(response)}")
		return ConversationResult(conversation_id=conv, response=response, model=model)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		"""Continue a session via `claude --resume <id> -p`. The JSON `result` is the
		latest turn's output (not accumulated), so no prefix-stripping is needed."""
		if not conversation_id:
			logger.warning("[ClaudeBridge] continue_conversation without conversation_id → prompt()")
			return self.prompt(text, timeout=timeout)
		try:
			data = self._run_claude(["--resume", conversation_id, "-p", text], timeout)
		except Exception as e:
			return ConversationResult(conversation_id=conversation_id, response="", error=str(e))
		return ConversationResult(
			conversation_id=data.get("session_id", conversation_id),
			response=str(data.get("result", "")),
		)

	def health_check(self) -> bool:
		"""Quick connectivity test — sends a minimal prompt."""
		try:
			result = self.prompt("Responde SOLO: OK", timeout=30)
			return result.ok and "OK" in result.response
		except Exception:
			return False
