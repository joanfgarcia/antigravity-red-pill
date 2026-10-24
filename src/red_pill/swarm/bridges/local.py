"""
LocalBridge — Execution backend using a LOCAL model via red-pill's inference
providers (SIP / llama.cpp).

A GENERATION backend: implements prompt() by calling the configured inference
provider. It is NOT a tool-using agent — capabilities report mcp_tools=False and
conversation_resume=False. Use it to route cheap agent-style tasks (summaries,
analysis, drafts) off-cloud to the local model.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from typing import Any, Dict, Optional

from .base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

logger = logging.getLogger(__name__)


class LocalBridge(AgentBridge):
	"""Execution backend: local model (SIP / llama.cpp) via the inference provider."""

	def __init__(self, provider=None, model_profile: Optional[str] = None):
		self._provider = provider
		self._model_profile = model_profile

	def _get_provider(self):
		if self._provider:
			return self._provider
		from red_pill.core.providers import ProviderRegistry

		prov = ProviderRegistry.get_inference_provider("sip")
		if not prov:
			raise RuntimeError("No local inference provider available (SIP).")
		return prov

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.LOCAL,
			auto_approve=False,
			ephemeral_mode=True,
			conversation_resume=False,
			model_selection=True,
			mcp_tools=False,
		)

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		# effort/cwd: N/A for the local generation backend (no subprocess, no effort knob).
		try:
			provider = self._get_provider()
			response = provider.generate(prompt=text, messages=[{"role": "user", "content": text}], temperature=0.3)
		except Exception as e:
			return ConversationResult(conversation_id="", response="", error=str(e))
		return ConversationResult(
			conversation_id=uuid_mod.uuid4().hex[:12],
			response=str(response),
			model=self._model_profile or "local",
		)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		# Local generation backend is stateless — no native multi-turn session.
		return self.prompt(text, timeout=timeout)

	def health_check(self) -> bool:
		try:
			return self._get_provider() is not None
		except Exception:
			return False


class LocalToolBridge(AgentBridge):
	"""Execution backend: local model with a bounded in-process TOOL loop.

	Where LocalBridge does a single generation, this runs
	local_minion.run_local_minion(): the model may call RedPill-Kernel MCP tools +
	bash until it answers or hits the loop cap. Best for short, concrete, headless
	tasks — see docs/TECHNICAL/MINIONS.md for capabilities and limits.
	"""

	def __init__(
		self,
		model_profile: Optional[str] = None,
		continuity_id: Optional[str] = None,
		mission_id: Optional[str] = None,
		originator: str = "",
		history_turns: int = 20,
		run_ref: Optional[str] = None,
		context_tokens: Optional[int] = None,
	):
		self._model_profile = model_profile
		self._continuity_id = continuity_id
		self._mission_id = mission_id
		self._originator = originator
		self._history_turns = history_turns
		self._run_ref = run_ref
		self._context_tokens = context_tokens

	@property
	def continuity_id(self) -> Optional[str]:
		return self._continuity_id

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.LOCAL,
			auto_approve=True,  # tools run without a human gate (loop is bounded)
			ephemeral_mode=True,
			conversation_resume=True,  # historial en el espejo cuando hay continuity_id
			model_selection=False,
			mcp_tools=True,
		)

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		# Bounded local tool loop. Must be called OFF the event loop (AgentMinion uses
		# asyncio.to_thread); we spin our own loop and enforce a wall-clock timeout on
		# top of the loop's own iteration/error caps.
		import asyncio

		from red_pill.swarm.agents.local_minion import run_local_minion

		extra: Dict[str, Any] = {"cwd": cwd}
		if self._continuity_id or self._mission_id or self._originator:
			extra.update(
				continuity_id=self._continuity_id,
				mission_id=self._mission_id,
				originator=self._originator,
				history_turns=self._history_turns,
				run_ref=self._run_ref,
			)
			if self._context_tokens is not None:
				extra["context_tokens"] = self._context_tokens
		try:
			result = asyncio.run(
				asyncio.wait_for(
					run_local_minion(text, **extra),
					timeout=timeout,
				)
			)
		except asyncio.TimeoutError:
			return ConversationResult(conversation_id="", response="", error=f"local-tools minion timed out after {timeout}s")
		except Exception as e:
			return ConversationResult(conversation_id="", response="", error=str(e))

		answer = result.get("answer", "")
		used_tools = result.get("used_tools")
		if result.get("ok"):
			# A tool-using backend with no SUCCESSFUL tool call produced an
			# UNGROUNDED answer — the model can invent a tool (or only collect
			# errors) and fabricate the output. Flag it so callers don't treat it
			# as a verified result. (Only when the loop reported it explicitly;
			# older/other callers omit it.)
			error = "local-tools produced no successful tool call (ungrounded answer)" if used_tools is False else None
		else:
			error = answer or "minion did not finish"
		return ConversationResult(
			conversation_id=uuid_mod.uuid4().hex[:12],
			response=answer,
			model=self._model_profile or "local-tools",
			error=error,
		)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		# Stateless — each run is a fresh bounded loop.
		return self.prompt(text, timeout=timeout)

	def health_check(self) -> bool:
		try:
			from red_pill.core.providers import ProviderRegistry

			return ProviderRegistry.get_inference_provider("sip") is not None
		except Exception:
			return False
