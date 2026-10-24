"""Contracts for the composable local harness.

The pieces are deliberately small and independent: a provider speaks OpenAI
chat, a toolbox exposes a schema plus an executor, and a profile binds a body
(name/role/prompt/model policy/toolbox) to those pieces. Jobs, swarm minions and
the smoke are compositions of these contracts, not copies of the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ChatProvider(Protocol):
	"""OpenAI-compatible chat client (UDS, localhost or remote)."""

	def chat(
		self,
		messages: List[Dict[str, Any]],
		*,
		tools: Optional[List[dict]] = None,
		tool_choice: Any = None,
		temperature: float = 0.0,
		max_tokens: int = 1024,
		timeout: Optional[int] = None,
	) -> Dict[str, Any]: ...


@runtime_checkable
class Toolbox(Protocol):
	"""A set of tool schemas plus their executor (workspace, MCP, read-only…)."""

	schemas: List[dict]

	def execute(self, name: str, arguments: Dict[str, Any]) -> str: ...


@dataclass(frozen=True)
class AgentProfile:
	"""A body: identity, role, provider/toolbox keys and generation policy."""

	key: str
	name: str
	role: str
	provider: str
	toolbox: Optional[str] = None
	system_prompt: str = ""
	max_steps: int = 16
	history_turns: int = 20
	temperature: float = 0.0
	max_tokens: int = 2048

	def render_system(self, *, session_short: str, operator: str) -> str:
		"""Render the short identity prompt; no Búnker/handshake placeholders."""
		return self.system_prompt.format(
			name=self.name,
			role=self.role,
			session_short=session_short,
			operator=operator,
		)
