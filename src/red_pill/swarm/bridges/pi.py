"""
PiBridge — Execution backend using the Pi CLI (pi-coding-agent, `pi`).

Runs headless via ``pi --mode json`` (non-interactive, structured event stream;
the JSON stream keeps the session header so the conversation can be resumed with
``--session <id>``). Sessions are saved to ``~/.pi/agent/sessions/``, so the
turn is also archived by the chronicle source (``chronicle_sources/pi``).

Identity loading and RAG are NOT injected by the bridge: when the red-pill
harness extension is deployed (``~/.pi/agent/extensions/red-pill.ts``, seeded by
``scripts/inject/pi/``), Pi fires the extension's events on every headless run —
``before_agent_start`` injects ``[BÚNKER IDENTIDAD]`` / ``[BÚNKER CONTEXTO]``,
``agent_end`` relays the turn to the memory queue. The bridge skips its own
scribe relay when that extension is present (no double-queueing).

Pi does not support MCP; the extension is the Búnker bridge. This backend is
registered as ``"pi"`` in the bridge factory (run_agent_task, agentic_job,
IDE_BACKEND).

Requirements:
- Pi CLI installed and on the CALLING process PATH (service managers need the
	install dir in ``Environment="PATH=..."``). Env override: ``PI_BIN``.
- A provider/model configured for Pi (the operator's ``~/.pi/agent/settings.json``).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.core.paths import get_bunker_root

from .base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

logger = logging.getLogger(__name__)

PI_BIN = "pi"


def _resolve_pi_bin() -> Optional[str]:
	"""Resolve the Pi CLI: env override → PATH."""
	if env_path := os.environ.get("PI_BIN"):
		return env_path
	return shutil.which(PI_BIN)


def _text_of(content: Any) -> str:
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text"))
	return ""


class PiBridge(AgentBridge):
	"""Execution backend: Pi CLI, headless (--mode json), sessions persisted."""

	def __init__(self, pi_path: Optional[str] = None, origin: str = "pi"):
		resolved = pi_path or _resolve_pi_bin()
		if not resolved:
			raise RuntimeError(
				"Pi CLI (pi) not found. Install pi-coding-agent and ensure `pi` is on the "
				"service manager's PATH (Linux: Environment= in ~/.config/systemd/user/*.service), "
				"or set PI_BIN."
			)
		self._pi_path = resolved
		self._origin = origin
		# When the red-pill harness extension is deployed, Pi itself relays the
		# turn (agent_end) and injects identity/RAG (before_agent_start) — the
		# bridge skips its own scribe to avoid double-queueing.
		self._extension_present = os.path.exists(Path.home() / ".pi" / "agent" / "extensions" / "red-pill.ts")

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.PI,
			auto_approve=True,  # headless: no approval prompts
			ephemeral_mode=False,  # sesiones persistidas → las archiva chronicle_sources/pi
			conversation_resume=True,
			model_selection=True,
			mcp_tools=False,  # Pi no soporta MCP; el puente es la extensión
		)

	def _run_pi(self, args: List[str], timeout: int, cwd: Optional[str] = None) -> Dict[str, Any]:
		cmd = [self._pi_path, "--mode", "json", "--approve", *args]
		logger.debug(f"[PiBridge] Running: {cmd[:4]}... (timeout={timeout}s, cwd={cwd or 'default'})")
		try:
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=timeout + 10,
				cwd=cwd or str(get_bunker_root().parent),
			)
		except subprocess.TimeoutExpired as e:
			logger.error(f"[PiBridge] Command timed out after {timeout + 10}s")
			raise RuntimeError(f"pi timed out after {timeout}s") from e

		if result.returncode != 0:
			stderr = (result.stderr or "").strip()
			logger.error(f"[PiBridge] pi failed (rc={result.returncode}): {stderr[:500]}")
			raise RuntimeError(f"pi failed (rc={result.returncode}): {stderr[:300]}")

		return self._parse_json_stream(result.stdout or "")

	@staticmethod
	def _parse_json_stream(stdout: str) -> Dict[str, Any]:
		"""Parse Pi's `--mode json` event stream.

		- session_id: the `id` of the first `session` (header) event.
		- text: text blocks of every `message_end` with role == assistant
			(concatenated — the final answer for one-shot runs).
		"""
		session_id = ""
		texts: List[str] = []
		for line in stdout.strip().splitlines():
			line = line.strip()
			if not line:
				continue
			try:
				event = json.loads(line)
			except json.JSONDecodeError:
				continue
			event_type = event.get("type", "")
			if event_type == "session" and not session_id:
				session_id = event.get("id", "")
			elif event_type == "message_end":
				msg = event.get("message", {})
				if msg.get("role") == "assistant":
					text = _text_of(msg.get("content"))
					if text.strip():
						texts.append(text)
		return {"session_id": session_id, "text": "\n".join(texts)}

	@staticmethod
	def _model_args(model: str) -> List[str]:
		if not model or model == "flash":
			return []
		return ["--model", model]

	@staticmethod
	def _effort_args(effort: Optional[str]) -> List[str]:
		# Portable standard (low|medium|high) → Pi --thinking levels.
		# medium → omit (model default); low/high map 1:1.
		mapped = {"low": "low", "high": "high"}.get((effort or "").strip().lower())
		return ["--thinking", mapped] if mapped else []

	def _scribe_relay(self, user_prompt: str, agent_response: str, model: Optional[str] = None):
		"""External Scribe: queue the turn unless the harness extension does it."""
		if self._extension_present:
			return
		try:
			from red_pill.core.queue_manager import MemoryQueueManager

			MemoryQueueManager().enqueue_memory(
				prompt=user_prompt,
				response=agent_response,
				role="assistant",
				originator="pi",
				model=model,
			)
			logger.debug("[PiBridge] Turn queued for ingestion (originator=pi)")
		except Exception as e:
			logger.warning(f"[PiBridge] Scribe relay failed (non-fatal): {e}")

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		try:
			data = self._run_pi(
				[*self._model_args(model), *self._effort_args(effort), text],
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
				error="pi returned empty text response",
			)

		try:
			self._scribe_relay(user_prompt=text, agent_response=response, model=model)
		except Exception as e:
			logger.warning(f"[PiBridge] Scribe relay failed (non-fatal): {e}")

		logger.info(f"[PiBridge] prompt() → session={session_id}, response_len={len(response)}")
		return ConversationResult(conversation_id=session_id, response=response, model=model)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		if not conversation_id:
			logger.warning("[PiBridge] continue_conversation without conversation_id → prompt()")
			return self.prompt(text, timeout=timeout)

		try:
			data = self._run_pi(
				["--session", conversation_id, text],
				timeout,
			)
		except Exception as e:
			return ConversationResult(conversation_id=conversation_id, response="", error=str(e))

		response = data.get("text", "")
		session_id = data.get("session_id") or conversation_id

		if not response:
			return ConversationResult(
				conversation_id=session_id,
				response="",
				error="pi returned empty text response",
			)

		try:
			self._scribe_relay(user_prompt=text, agent_response=response)
		except Exception as e:
			logger.warning(f"[PiBridge] Scribe relay failed (non-fatal): {e}")

		return ConversationResult(conversation_id=session_id, response=response)

	def health_check(self) -> bool:
		"""Quick connectivity test — sends a minimal prompt."""
		try:
			result = self.prompt("Responde SOLO: OK", timeout=30)
			return result.ok and "OK" in result.response
		except Exception:
			return False
