"""
AgentBridge — Abstract interface for running an agent backend (v2, generalized).

Generic abstraction for "run a prompt through an agent", independent of which
backend executes it. Implementations:
- AgyBridge     (antigravity_ide): agy CLI               — execution
- ClaudeBridge  (swarm/bridges):  claude CLI            — execution
- OpenCodeBridge(swarm/bridges):  opencode CLI          — execution
- LocalBridge   (swarm/bridges):  local model (SIP)     — generation
- GrpcBridge    (antigravity_ide): gRPC to LanguageServer — extraction (Chronicle)

Was `IDEBridge` under plugins/antigravity_ide; moved here once it stopped being
Antigravity-specific. Antigravity-only backends still live in antigravity_ide and
import this ABC from here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class NotSupportedError(Exception):
	"""Raised when a feature is not available on the current backend."""

	pass


class BackendType(Enum):
	AGY = "agy"
	GRPC = "grpc"
	CLAUDE = "claude"
	OPENCODE = "opencode"
	LOCAL = "local"


@dataclass
class ConversationResult:
	"""Result from creating or continuing a conversation."""

	conversation_id: str
	response: str
	model: Optional[str] = None
	error: Optional[str] = None
	# Accumulated stdout length — used for prefix-stripping in multi-turn
	accumulated_len: int = 0

	@property
	def ok(self) -> bool:
		return self.error is None


@dataclass
class BridgeCapabilities:
	"""What the current backend supports."""

	backend: BackendType
	auto_approve: bool = False  # Can skip tool approval prompts
	ephemeral_mode: bool = False  # Conversations don't pollute IDE
	conversation_resume: bool = False  # Can continue previous conversations
	model_selection: bool = False  # Can choose model (flash/pro)
	mcp_tools: bool = False  # Agent can use MCP tools autonomously


# ── Standard effort vocabulary (portable) ──────────────────────────────────
# red-pill exposes ONE standard effort scale; each bridge MAPS it to its platform's
# real control: ClaudeBridge → `--effort`; AgyBridge → the model's "(Mode)" variant
# (agy fuses model+mode in the model name); OpenCodeBridge → `--variant`;
# LocalBridge → ignored (no effort knob).
# Callers (skills, the bot) speak this standard and never the platform-specific value.
STANDARD_EFFORTS = ("low", "medium", "high")


class AgentBridge(ABC):
	"""Abstract interface for agent-backend communication.

	Subclasses must implement the execution methods (prompt, continue_conversation,
	health_check). Extraction methods (get_all_trajectories, get_trajectory_steps)
	have default NotSupportedError implementations — only GrpcBridge overrides them.
	"""

	@abstractmethod
	def get_capabilities(self) -> BridgeCapabilities:
		"""Return what this backend supports."""
		...

	@abstractmethod
	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 120,
	) -> ConversationResult:
		"""Send a one-shot prompt and get a response.

		This is the primary method for both Neon-Link commands
		(Telegram, Minion Inbox, etc.) and autonomous AWAKENINGs.

		effort: backend-specific reasoning-effort hint (e.g. claude
			--effort low|medium|high|xhigh|max). None → backend default.
			Ignored by backends that don't support it.
		cwd: working directory the agent operates in (the target
			workspace/project). None → backend default. Lets the caller
			point the agent at a specific project instead of red-pill's dir.
		"""
		...

	@abstractmethod
	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		"""Continue an existing conversation. Used for multi-turn sessions."""
		...

	@abstractmethod
	def health_check(self) -> bool:
		"""Quick connectivity test."""
		...

	# --- Extraction methods (Chronicle pipeline) ---
	# Default: NotSupportedError. Only GrpcBridge overrides.

	def get_all_trajectories(self) -> List[Dict[str, Any]]:
		"""List all conversation summaries from the IDE (GrpcBridge only)."""
		raise NotSupportedError(
			f"{type(self).__name__} does not support conversation extraction. Use GrpcBridge (create_extraction_bridge()) for Chronicle pipeline."
		)

	def get_trajectory_steps(self, cascade_id: str, start_index: int = 0, end_index: int = 1000) -> List[Dict[str, Any]]:
		"""Get all steps for a specific conversation (GrpcBridge only)."""
		raise NotSupportedError(
			f"{type(self).__name__} does not support conversation extraction. Use GrpcBridge (create_extraction_bridge()) for Chronicle pipeline."
		)
