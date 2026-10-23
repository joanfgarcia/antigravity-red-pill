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
from red_pill.session.identity import new_continuity_id
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry
from red_pill.session.switch import replay_messages

logger = logging.getLogger(__name__)


@dataclass
class MiniConfig:
	workspace: str
	continuity_id: Optional[str] = None
	mission_id: str = "mission:mini-smoke"
	campaign_id: Optional[str] = None
	db_path: Optional[str] = None
	affinity: List[str] = field(default_factory=lambda: ["mission:mini-smoke"])
	body_names: Dict[str, str] = field(default_factory=lambda: {"forge": "Forge", "loom": "Loom"})
	max_steps: int = 16
	history_turns: int = 40
	temperature: float = 0.0
	max_tokens: int = 2048


class MiniSession:
	"""One soul, two bounded bodies (Forge on GPU, Loom on NPU)."""

	def __init__(self, config: MiniConfig, providers: Dict[str, Any]):
		self.config = config
		self.providers = providers
		self.continuity_id = config.continuity_id or new_continuity_id()
		self.mirror = SessionMirror(config.db_path)
		self.registry = SessionRegistry(self.mirror.db_path)
		self.run_id = uuid.uuid4().hex[:12]
		self.phase = 0
		self.current_body: Optional[str] = None
		self.current_originator: Optional[str] = None
		self.affinity = canonize_affinity(config.affinity)

	def _leg(self, body: str) -> str:
		return f"{body}:{self.run_id}"

	def _ensure_leg(self, body: str, role: str) -> str:
		originator = self._leg(body)
		self.registry.upsert_session(
			originator=originator,
			continuity_id=self.continuity_id,
			mission_id=self.config.mission_id,
			campaign_id=self.config.campaign_id,
			role=role,
			affinity=self.affinity,
			title=self.config.body_names.get(body, body),
		)
		return originator

	def switch_to(self, body: str, role: str) -> str:
		"""Migrate the soul to `body`: close the old leg, open the new one."""
		old = self.current_originator
		if old and old != self._leg(body):
			self.registry.unregister_session(old)
		originator = self._ensure_leg(body, role)
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
				title=self.config.body_names.get(body, body),
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

	def _append(self, role: str, content: Optional[str], *, tool_calls: Any = None, tool_call_id: Optional[str] = None, source_ref: str) -> None:
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
	) -> Dict[str, Any]:
		"""Run one task on `body`; returns text, messages and tool statistics."""
		if body not in self.providers:
			raise ValueError(f"no provider for body {body!r}")
		if self.current_body != body:
			self.switch_to(body, role)
		self.phase += 1
		phase_ref = f"{self.run_id}:p{self.phase}"
		turns = self.mirror.read_turns(self.continuity_id)
		if self.config.history_turns > 0:
			turns = turns[-self.config.history_turns :]
		messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
		messages.extend(replay_messages(turns, current_prompt=task))
		self._append("user", task, source_ref=f"{phase_ref}:user")

		provider = self.providers[body]
		steps = int(max_steps or self.config.max_steps)
		tool_calls_made = 0
		last_text = ""
		transcript: List[Dict[str, Any]] = []
		for step in range(max(steps, 1)):
			assistant = provider.chat(
				messages,
				tools=tools,
				temperature=self.config.temperature,
				max_tokens=self.config.max_tokens,
			)
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
			self._append("assistant", content, tool_calls=calls, source_ref=f"{phase_ref}:a{step}")
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
				result = self._execute_tool(executor, name, args)
				tool_message = {"role": "tool", "tool_call_id": call_id, "content": result}
				messages.append(tool_message)
				self._append("tool", result, tool_call_id=call_id, source_ref=f"{phase_ref}:t{step}-{index}")
				transcript.append(tool_message)
		return {
			"body": body,
			"text": last_text,
			"steps": len(transcript),
			"tool_calls": tool_calls_made,
			"messages": messages,
			"transcript": transcript,
		}

	@staticmethod
	def _execute_tool(executor: Any, name: str, args: Dict[str, Any]) -> str:
		execute = getattr(executor, "execute", None)
		if callable(execute):
			return str(execute(name, args))
		raise ValueError("executor must expose execute(name, args)")
