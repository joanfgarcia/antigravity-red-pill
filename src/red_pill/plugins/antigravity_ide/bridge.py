"""
IDEBridge — Abstract Interface for Antigravity IDE Communication (v2)

Two complementary implementations:
  - AgyBridge (execution): agy CLI with --dangerously-skip-permissions
  - GrpcBridge (extraction): gRPC-Web to LanguageServer (Chronicle pipeline)

Both bridges can coexist. AgyBridge for prompt execution (Telegram, AWAKENINGs).
GrpcBridge for conversation extraction (Chronicle → archive_memories).
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


class IDEBridge(ABC):
	"""Abstract interface for Antigravity IDE communication.

	Subclasses must implement the execution methods (prompt, continue_conversation,
	health_check). Extraction methods (get_all_trajectories, get_trajectory_steps)
	have default NotSupportedError implementations — only GrpcBridge overrides them.
	"""

	@abstractmethod
	def get_capabilities(self) -> BridgeCapabilities:
		"""Return what this backend supports."""
		...

	@abstractmethod
	def prompt(self, text: str, *, model: str = "flash", timeout: int = 120) -> ConversationResult:
		"""Send a one-shot prompt and get a response.

		This is the primary method for both Neon-Link commands
		(Telegram, Minion Inbox, etc.) and autonomous AWAKENINGs.
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
		"""Continue an existing conversation.

		Used for multi-turn Telegram sessions.
		Args:
			conversation_id: UUID from the first prompt() call.
			previous_response_len: Accumulated stdout length for prefix-stripping.
		"""
		...

	@abstractmethod
	def health_check(self) -> bool:
		"""Quick connectivity test."""
		...

	# --- Extraction methods (Chronicle pipeline) ---
	# Default: NotSupportedError. Only GrpcBridge overrides.

	def get_all_trajectories(self) -> List[Dict[str, Any]]:
		"""List all conversation summaries from the IDE.

		Used by Chronicle to discover new conversations for archive ingestion.
		Only supported by GrpcBridge.
		"""
		raise NotSupportedError(
			f"{type(self).__name__} does not support conversation extraction. "
			"Use GrpcBridge (create_extraction_bridge()) for Chronicle pipeline."
		)

	def get_trajectory_steps(self, cascade_id: str, start_index: int = 0, end_index: int = 1000) -> List[Dict[str, Any]]:
		"""Get all steps for a specific conversation.

		Used by Chronicle to extract and decrypt conversation content.
		Only supported by GrpcBridge.
		"""
		raise NotSupportedError(
			f"{type(self).__name__} does not support conversation extraction. "
			"Use GrpcBridge (create_extraction_bridge()) for Chronicle pipeline."
		)
