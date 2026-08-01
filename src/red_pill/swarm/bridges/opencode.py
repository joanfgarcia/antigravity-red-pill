"""
OpenCodeBridge — Execution backend using the OpenCode CLI (`opencode`).

Uses `opencode run --format json --auto` for headless, auto-approved prompt
execution.  The JSON output is a stream of events; we extract the session ID
from step_start events and the response text from text events.

Identity loading and scribe relay are handled at the transport layer (like the
Antigravity worker), not delegated to the model.  The bridge injects a handshake
preamble into every prompt and queues each turn into `memory_queue`, the single
sink the kernel's worker drains into `interaction_memories`.

Two execution modes:

1. **Direct** (default): ``opencode run`` — cold start, MCP servers initialize
	per call.  Zero dependencies beyond the opencode CLI.

2. **Attached**: ``opencode run --attach <url>`` — reuses a persistent
	``opencode serve`` instance, avoiding MCP cold-start.  Set
	``OPENCODE_SERVER_URL`` env var or pass ``server_url`` to the constructor.

Requirements:
- opencode CLI installed and configured (~/.config/opencode/).
- The `opencode` binary must be resolvable from the CALLING process. Service
	managers run with a minimal PATH: on Linux add the install dir to
	`Environment="PATH=..."` in ~/.config/systemd/user/*.service (equivalent:
	launchd plist on macOS, Task Scheduler env on Windows). The bridge also
	honours OPENCODE_BIN and probes ~/.opencode/bin as a last resort.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from red_pill.core.paths import get_bunker_root

from .base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

logger = logging.getLogger(__name__)

OPENCODE_BIN = "opencode"


def _resolve_opencode_bin() -> Optional[str]:
	"""Resolve the opencode CLI: env override → PATH → well-known install dir.

	Service managers (systemd user units, launchd, Task Scheduler) run with a
	minimal PATH that rarely includes user-local bin dirs, so probe the
	standard install location as a last resort.
	"""
	if env_path := os.environ.get("OPENCODE_BIN"):
		return env_path
	if found := shutil.which(OPENCODE_BIN):
		return found
	exe = "opencode.exe" if os.name == "nt" else OPENCODE_BIN
	candidate = Path.home() / ".opencode" / "bin" / exe
	return str(candidate) if candidate.is_file() else None


class OpenCodeBridge(AgentBridge):
	"""Execution backend: OpenCode CLI, headless + auto-approved.

	Identity loading and scribe relay are handled by the bridge itself,
	not by the model.  Every prompt gets a handshake preamble that instructs
	the agent to load its identity; every turn is queued for ingestion via
	the External Scribe Pattern.
	"""

	def __init__(
		self,
		opencode_path: Optional[str] = None,
		server_url: Optional[str] = None,
		identity_depth: str = "medium",
	):
		self._opencode_path = opencode_path or _resolve_opencode_bin()
		if not self._opencode_path:
			raise RuntimeError(
				"OpenCode CLI (opencode) not found. Install OpenCode and ensure `opencode` is "
				"on the service manager's PATH (Linux: Environment= in ~/.config/systemd/user/*.service; "
				"macOS: launchd plist; Windows: Task Scheduler env), or set OPENCODE_BIN."
			)
		# Priority: explicit param > env var > default
		self._server_url = server_url or os.environ.get("OPENCODE_SERVER_URL", "")
		self._identity_depth = identity_depth
		# When the opencode session runs under the redpill-scribe plugin, the
		# plugin already captures the turn. Skipping here is the cheap guard; the
		# hash check in enqueue_memory is the one that actually guarantees it.
		self._scribe_plugin = os.environ.get("OPENCODE_SCRIBE_PLUGIN", "").lower() == "true"

	# ── Handshake preamble ────────────────────────────────────────────────
	# OpenCode does NOT prefix MCP tools (unlike Antigravity's mcp_<server>_<tool>).
	# Tools appear under resource group names: bunker_memory_api, swarm_orchestrator_api.

	def _build_handshake_preamble(self, user_prompt: str) -> str:
		"""Build the identity-loading preamble injected before every prompt.

		Uses OpenCode-native tool names (no mcp_ prefix).  The preamble
		instructs the agent to:
		1. Call interceptor_rp to fetch real-time telemetry (pain signals, activity).
		2. Call refresh_session_context to load identity from the Bünker.
		3. Adopt the BUNKER_CONTEXT as session identity.

		Persistence (scribe relay) is handled by the bridge _scribe_relay()
		directly — the agent does NOT need to persist the turn.
		"""
		depth = self._identity_depth
		return (
			f"<user_rules>\n"
			f"<RULE[user_global]>\n"
			f'<constraint critical="true" level="0" name="telegram_session">\n'
			f"CRITICAL: Respond ONLY to the <current_message> below. The history is for context only.\n"
			f"MANDATORY FIRST STEPS:\n"
			f'1. Call `swarm_orchestrator_api` with {{"action": "interceptor_rp", "payload": {{"user_prompt": "<the current_message text>", "mode": "{depth}"}}}} to fetch real-time telemetry (pain signals, emotional sync, activity status).\n'
			f'2. Call `bunker_memory_api` with {{"action": "refresh_session_context", "payload": {{"mode": "{depth}"}}}} to load your identity from the Bünker.\n'
			f"3. Adopt the <BUNKER_CONTEXT> as your session identity and respond.\n"
			f"</constraint>\n"
			f"</RULE[user_global]>\n"
			f"</user_rules>\n\n"
			f"<current_message>\n{user_prompt}\n</current_message>\n"
		)

	# ── Scribe relay (External Scribe Pattern) ────────────────────────────

	def _scribe_relay(self, user_prompt: str, agent_response: str, model: Optional[str] = None, originator: str = "opencode"):
		"""Queue prompt + response for ingestion, with no dependency on the agent.

		Headless bridges (Telegram, agentic jobs) have no editor hook to capture
		the turn for them, so the bridge captures it itself. It goes to the ONE
		queue the worker drains into `interaction_memories` — the turn becomes a
		memory instead of landing in a table nobody reads.
		"""
		try:
			from red_pill.core.queue_manager import MemoryQueueManager

			MemoryQueueManager().enqueue_memory(
				prompt=user_prompt,
				response=agent_response,
				role="assistant",
				originator=originator,
				model=model,
			)
			logger.debug(f"[Scribe] Turn queued for ingestion (originator={originator})")
		except Exception as e:
			# Non-fatal: log but don't block the pipeline
			logger.warning(f"[Scribe] Failed to queue interaction: {e}")

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
		"""Send a one-shot prompt via ``opencode run``.

		Injects the handshake preamble before the prompt and queues the turn
		for ingestion after receiving the response.
		"""
		wrapped_prompt = self._build_handshake_preamble(text)

		try:
			data = self._run_opencode(
				[wrapped_prompt, *self._model_args(model), *self._effort_args(effort)],
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

		# External Scribe: persist interaction directly (non-fatal)
		# Skip if redpill-scribe plugin handles persistence via hooks
		if not self._scribe_plugin:
			try:
				self._scribe_relay(user_prompt=text, agent_response=response, model=model)
			except Exception as e:
				logger.warning(f"[OpenCodeBridge] Scribe relay failed (non-fatal): {e}")

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

		wrapped_prompt = self._build_handshake_preamble(text)

		try:
			data = self._run_opencode(
				["-s", conversation_id, wrapped_prompt],
				timeout,
			)
		except Exception as e:
			return ConversationResult(conversation_id=conversation_id, response="", error=str(e))

		response = data.get("text", "")

		# External Scribe — skip if plugin handles it
		if not self._scribe_plugin:
			try:
				self._scribe_relay(user_prompt=text, agent_response=response)
			except Exception as e:
				logger.warning(f"[OpenCodeBridge] Scribe relay failed (non-fatal): {e}")

		return ConversationResult(
			conversation_id=data.get("session_id", conversation_id),
			response=response,
		)

	def health_check(self) -> bool:
		"""Quick connectivity test — sends a minimal prompt."""
		try:
			result = self.prompt("Responde SOLO: OK", timeout=30)
			return result.ok and "OK" in result.response
		except Exception:
			return False
