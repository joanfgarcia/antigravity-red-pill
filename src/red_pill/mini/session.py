"""Mini session runner: Forge/Loom over the canonical session mirror.

The model only receives a short system prompt (identity + rules), the replayed
history and the task. There is no handshake, no Búnker, no RAG and no session
tag. The mirror is the memory; switching bodies is a registry migration with the
same `continuity_id`.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from red_pill.core.affinity import canonize_affinity
from red_pill.mini.contracts import AgentProfile, Toolbox
from red_pill.session.compactor import Compactor, estimate_tokens, is_context_length_error
from red_pill.session.identity import new_continuity_id
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry
from red_pill.session.switch import replay_messages, trim_history_chars, trim_history_window

logger = logging.getLogger(__name__)


@dataclass
class MiniConfig:
	workspace: str
	continuity_id: Optional[str] = None
	mission_id: str = "mission:mini-smoke"
	campaign_id: Optional[str] = None
	db_path: Optional[str] = None
	run_ref: Optional[str] = None
	lineage_id: Optional[str] = None
	affinity: List[str] = field(default_factory=lambda: ["mission:mini-smoke"])
	operator: str = "Joan"
	body_names: Dict[str, str] = field(default_factory=lambda: {"forge": "Forge", "loom": "Loom"})
	max_steps: int = 8
	history_turns: int = 12
	history_max_chars: int = 12000
	temperature: float = 0.0
	max_tokens: int = 2048
	context_tokens: int = 8192
	compactor_enabled: Optional[bool] = None
	compactor_engine: Optional[str] = None
	compactor_protect_last_n: Optional[int] = None


class MiniSession:
	"""One soul, two bounded bodies (Forge on GPU, Loom on NPU)."""

	def __init__(
		self,
		config: MiniConfig,
		providers: Dict[str, Any],
		*,
		profiles: Optional[Dict[str, AgentProfile]] = None,
		toolboxes: Optional[Dict[str, Toolbox]] = None,
		compactor: Optional[Compactor] = None,
	):
		self.config = config
		self.providers = providers
		self.profiles = profiles or {}
		self.toolboxes = toolboxes or {}
		self.continuity_id = config.continuity_id or new_continuity_id()
		self.mirror = SessionMirror(config.db_path)
		self.registry = SessionRegistry(self.mirror.db_path)
		self.run_id = str(config.run_ref or uuid.uuid4().hex[:12])
		self.phase = 0
		self.current_body: Optional[str] = None
		self.current_originator: Optional[str] = None
		self.affinity = canonize_affinity(config.affinity)
		self.compactor = compactor or self._build_compactor()

	def _build_compactor(self) -> Optional[Compactor]:
		enabled = self.config.compactor_enabled
		if enabled is None:
			try:
				import red_pill.config as cfg

				enabled = bool(getattr(cfg.get_config(), "SESSION_COMPACTOR_ENABLED", False))
			except Exception:
				enabled = False
		if not enabled:
			return None
		return Compactor(
			self.mirror,
			engine=self.config.compactor_engine,
			protect_last_n=self.config.compactor_protect_last_n,
		)

	def _leg(self, body: str) -> str:
		return f"{body}:{self.run_id}"

	def _display_name(self, body: str) -> str:
		profile = self.profiles.get(body)
		if profile is not None:
			return profile.name
		return self.config.body_names.get(body, body)

	def _ensure_leg(self, body: str, role: str) -> str:
		originator = self._leg(body)
		self.registry.upsert_session(
			originator=originator,
			continuity_id=self.continuity_id,
			mission_id=self.config.mission_id,
			campaign_id=self.config.campaign_id,
			role=role,
			affinity=self.affinity,
			title=self._display_name(body),
		)
		return originator

	def switch_to(self, body: str, role: str) -> str:
		"""Migrate the soul to `body`: close the old leg, open the new one.

		`activate_leg` does the close + upsert in one `BEGIN IMMEDIATE`; a lock or
		crash cannot leave two active legs for the same soul.
		"""
		old = self.current_originator
		originator = self._leg(body)
		self.registry.activate_leg(
			originator=originator,
			continuity_id=self.continuity_id,
			mission_id=self.config.mission_id,
			campaign_id=self.config.campaign_id,
			role=role,
			lineage_id=self.config.lineage_id,
			affinity=self.affinity,
			title=self._display_name(body),
		)
		global_turn = 0
		try:
			global_turn = self.registry.next_global_turn(originator, self.affinity)
		except Exception:
			pass
		try:
			self.registry.upsert_session(
				originator=originator,
				continuity_id=self.continuity_id,
				mission_id=self.config.mission_id,
				campaign_id=self.config.campaign_id,
				role=role,
				affinity=self.affinity,
				title=self._display_name(body),
				last_seen_global_turn=global_turn,
			)
			self.registry.add_event(
				event_type="intent_updated",
				mission_id=self.config.mission_id,
				summary=f"switch {old or '?'}→{originator} ({role})",
				campaign_id=self.config.campaign_id,
				continuity_id=self.continuity_id,
				originator=originator,
				global_turn=global_turn,
			)
		except Exception as e:
			logger.warning(f"[MiniSession] switch publish failed: {e}")
		self.current_body = body
		self.current_originator = originator
		return originator

	def _append(
		self,
		role: str,
		content: Optional[str],
		*,
		tool_calls: Any = None,
		tool_call_id: Optional[str] = None,
		source_ref: str,
		request_id: Optional[str] = None,
	) -> None:
		self.mirror.append_turn(
			continuity_id=self.continuity_id,
			mission_id=self.config.mission_id,
			role=role,
			content=content,
			tool_calls=tool_calls,
			tool_call_id=tool_call_id,
			model=self.current_body,
			ts=time.time(),
			originator=self.current_originator or "",
			source=self.current_body or "",
			source_ref=source_ref,
			request_id=request_id,
			status="completed",
		)

	@staticmethod
	def _parse_arguments(raw: Any) -> Dict[str, Any]:
		if isinstance(raw, dict):
			return raw
		if not raw:
			return {}
		try:
			value = json.loads(raw)
		except (TypeError, ValueError):
			return {}
		return value if isinstance(value, dict) else {}

	def run(
		self,
		body: str,
		*,
		system_prompt: str,
		task: str,
		tools: Optional[List[dict]] = None,
		executor: Any = None,
		role: str = "executor",
		max_steps: Optional[int] = None,
		provider_key: Optional[str] = None,
		temperature: Optional[float] = None,
		max_tokens: Optional[int] = None,
		history_turns: Optional[int] = None,
		timeout: Optional[int] = None,
		context_tokens: Optional[int] = None,
	) -> Dict[str, Any]:
		"""Run one task on `body`; returns text, messages and tool statistics."""
		provider_name = provider_key or body
		if provider_name not in self.providers:
			raise ValueError(f"no provider for body {provider_name!r}")
		if self.current_body != body:
			self.switch_to(body, role)
		self.phase += 1
		phase_ref = f"{self.run_id}:p{self.phase}"
		request_id = phase_ref
		turns = self.mirror.read_turns(self.continuity_id)
		if self.compactor is not None:
			budget = self.config.context_tokens if context_tokens is None else int(context_tokens)
			extra_tokens = estimate_tokens(system_prompt) + estimate_tokens(task)
			ctx = self.compactor.ensure_context(
				self.continuity_id,
				budget_tokens=budget,
				extra_tokens=extra_tokens,
				mission_id=self.config.mission_id,
			)
			turns = ctx.turns
			if not ctx.compacted and self.compactor.should_start_background(
				ctx.messages,
				extra_tokens=extra_tokens,
				budget_tokens=budget,
				reserve_tokens=self.compactor.reserve_tokens,
			):
				try:
					self.compactor.maybe_start(
						self.continuity_id,
						mission_id=self.config.mission_id,
						extra_tokens=extra_tokens,
						budget_tokens=budget,
						reserve_tokens=self.compactor.reserve_tokens,
					)
				except Exception as exc:
					logger.warning("[MiniSession] background compaction enqueue failed: %s", exc)
		limit = self.config.history_turns if history_turns is None else history_turns
		if limit > 0:
			turns = trim_history_window(turns, limit)
		turns = trim_history_chars(turns, self.config.history_max_chars)
		turns = trim_history_window(turns, len(turns))
		messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
		messages.extend(replay_messages(turns, current_prompt=task))
		self.mirror.begin_turn(
			continuity_id=self.continuity_id,
			mission_id=self.config.mission_id,
			request_id=request_id,
			content=task,
			originator=self.current_originator or "",
			source=self.current_body or "",
			model=body,
			source_ref=f"{phase_ref}:user",
		)

		provider = self.providers[provider_name]
		steps = int(max_steps or self.config.max_steps)
		temp = self.config.temperature if temperature is None else temperature
		limit_tokens = self.config.max_tokens if max_tokens is None else max_tokens
		tool_calls_made = 0
		last_text = ""
		transcript: List[Dict[str, Any]] = []
		length_retry_done = False
		for step in range(max(steps, 1)):
			try:
				assistant = provider.chat(
					messages,
					tools=tools,
					temperature=temp,
					max_tokens=limit_tokens,
					**( {"timeout": timeout} if timeout is not None else {} ),
				)
			except Exception as e:
				# Un rechazo por longitud no debe tumbar el turno: se compacta
				# una vez y se reintenta con el contexto reducido. El espejo y
				# el request_id no se tocan; el turno sigue siendo el mismo.
				if not length_retry_done and self.compactor is not None and is_context_length_error(e):
					length_retry_done = True
					try:
						done = self.compactor.compact_now(
							self.continuity_id,
							mission_id=self.config.mission_id,
							reason="length_retry",
						)
					except Exception as exc:
						logger.warning("[MiniSession] length-retry compaction failed: %s", exc)
						done = None
					if done is not None:
						turns = self.mirror.context_turns(self.continuity_id)
						if limit > 0:
							turns = trim_history_window(turns, limit)
						turns = trim_history_chars(turns, self.config.history_max_chars)
						turns = trim_history_window(turns, len(turns))
						messages = [{"role": "system", "content": system_prompt}]
						messages.extend(replay_messages(turns, current_prompt=task))
						logger.info("[MiniSession] context-length rejection; retrying with compacted context")
						continue
				self.mirror.abort_turn(
					continuity_id=self.continuity_id,
					request_id=request_id,
					reason=f"provider_error: {e}",
					mission_id=self.config.mission_id,
				)
				raise
			content = assistant.get("content")
			calls = assistant.get("tool_calls")
			calls = calls if isinstance(calls, list) else None
			if calls and (tools is None or executor is None):
				# Un cuerpo sin tools no puede ejecutar: se descartan las llamadas
				# (no se guardan parejas huérfanas) y se conserva el texto.
				calls = None
				if not content:
					content = "(tool calls are not available in this body)"
			assistant_turn = {"role": "assistant", "content": content, "tool_calls": calls}
			messages.append(assistant_turn)
			self._append("assistant", content, tool_calls=calls, source_ref=f"{phase_ref}:a{step}", request_id=request_id)
			transcript.append(assistant_turn)
			last_text = str(content or "")

			if not calls:
				break
			tool_calls_made += len(calls)
			for index, call in enumerate(calls):
				call = call if isinstance(call, dict) else {}
				fn = call.get("function") or {}
				name = str(fn.get("name") or "")
				args = self._parse_arguments(fn.get("arguments"))
				call_id = str(call.get("id") or f"{phase_ref}:call{step}-{index}")
				try:
					result = self._execute_tool(executor, name, args)
				except Exception as e:
					self.mirror.abort_turn(
						continuity_id=self.continuity_id,
						request_id=request_id,
						reason=f"tool_error: {e}",
						mission_id=self.config.mission_id,
					)
					raise
				tool_message = {"role": "tool", "tool_call_id": call_id, "content": result}
				messages.append(tool_message)
				self._append("tool", result, tool_call_id=call_id, source_ref=f"{phase_ref}:t{step}-{index}", request_id=request_id)
				transcript.append(tool_message)
		self.mirror.complete_turn(continuity_id=self.continuity_id, request_id=request_id)
		return {
			"body": body,
			"text": last_text,
			"steps": len(transcript),
			"tool_calls": tool_calls_made,
			"messages": messages,
			"transcript": transcript,
			"request_id": request_id,
		}

	def run_profile(self, profile_name: str, task: str, *, max_steps: Optional[int] = None, timeout: Optional[int] = None) -> Dict[str, Any]:
		"""Compose a profile (identity + provider + toolbox + policy) and run it."""
		profile = self.profiles.get(profile_name)
		if profile is None:
			raise ValueError(f"unknown profile: {profile_name!r}")
		toolbox = None
		if profile.toolbox:
			toolbox = self.toolboxes.get(profile.toolbox)
			if toolbox is None:
				raise ValueError(f"unknown toolbox: {profile.toolbox!r}")
		return self.run(
			profile.key,
			system_prompt=profile.render_system(session_short=self.continuity_id[:8], operator=self.config.operator),
			task=task,
			tools=toolbox.schemas if toolbox is not None else None,
			executor=toolbox,
			role=profile.role,
			max_steps=profile.max_steps if max_steps is None else max_steps,
			provider_key=profile.provider,
			temperature=profile.temperature,
			max_tokens=profile.max_tokens,
			history_turns=profile.history_turns,
			timeout=timeout,
			context_tokens=profile.context_tokens or None,
		)

	@staticmethod
	def _execute_tool(executor: Any, name: str, args: Dict[str, Any]) -> str:
		execute = getattr(executor, "execute", None)
		if callable(execute):
			return str(execute(name, args))
		raise ValueError("executor must expose execute(name, args)")
