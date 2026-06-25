"""
CascadeBridge — execution bridge with an ordered fallback cascade.

Wraps a list of BridgeTarget (backend + model + effort). prompt() tries each
target in order and returns the first result with quota (res.ok). If the list is
empty it raises NoModelsConfigured; if every target fails it raises
AllModelsExhausted carrying the per-target errors so the caller can surface the
pertinent error to the user.

This is the runtime of the configured cascade (config.TELEGRAM_BRIDGE_CASCADE);
the inbox/Telegram worker builds it via factory.create_cascade_bridge(). When no
cascade is configured the worker falls back to the single IDE_BACKEND bridge, so
this code path only runs when the operator opts in.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

from .base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

if TYPE_CHECKING:
	from red_pill.config import BridgeTarget

logger = logging.getLogger(__name__)


def _label(target: "BridgeTarget") -> str:
	"""Human-readable target label, e.g. 'claude/opus' or 'agy/default'."""
	return f"{target.backend}/{target.model or 'default'}"


class CascadeError(Exception):
	"""Base for cascade execution failures."""


class NoModelsConfigured(CascadeError):
	"""The cascade has no targets configured (empty list)."""


class AllModelsExhausted(CascadeError):
	"""Every target in the cascade failed — no model available / with quota.

	`errors` is the ordered list of (target, error_message) so the caller can
	build a user-facing message with the pertinent reason per model.
	"""

	def __init__(self, errors: List[Tuple["BridgeTarget", str]]):
		self.errors = errors
		detail = "; ".join(f"{_label(t)}: {e}" for t, e in errors) or "no targets"
		super().__init__(f"all cascade targets failed → {detail}")


class CascadeBridge(AgentBridge):
	"""AgentBridge that tries an ordered list of targets, first-with-quota wins."""

	def __init__(self, targets: "List[BridgeTarget]", name: str = "cascade"):
		self._targets: "List[BridgeTarget]" = list(targets or [])
		self._name = name

	def _build(self, backend: str) -> AgentBridge:
		# Lazy import to avoid a factory ↔ cascade import cycle.
		from .factory import create_bridge

		return create_bridge(backend)

	def _primary_bridge(self) -> Optional[AgentBridge]:
		"""First target that constructs successfully (for non-prompt delegation)."""
		for t in self._targets:
			try:
				return self._build(t.backend)
			except Exception:
				continue
		return None

	def get_capabilities(self) -> BridgeCapabilities:
		bridge = self._primary_bridge()
		if bridge is not None:
			return bridge.get_capabilities()
		return BridgeCapabilities(backend=BackendType.GRPC)

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		"""Try each target in order; return the first ok result.

		Raises NoModelsConfigured if the cascade is empty, or AllModelsExhausted
		(with per-target errors) if every target fails.
		"""
		if not self._targets:
			raise NoModelsConfigured(f"no bridge targets configured in {self._name}")

		errors: List[Tuple["BridgeTarget", str]] = []
		for t in self._targets:
			try:
				bridge = self._build(t.backend)
			except Exception as e:
				logger.warning(f"[CascadeBridge] {_label(t)} unavailable: {e}")
				errors.append((t, f"backend unavailable: {e}"))
				continue

			res = bridge.prompt(text, model=(t.model or model), effort=(t.effort or effort), cwd=cwd, timeout=timeout)
			if res.ok:
				logger.info(f"[CascadeBridge] served by {_label(t)}")
				return res

			logger.warning(f"[CascadeBridge] {_label(t)} failed: {res.error}")
			errors.append((t, res.error or "unknown error"))

		raise AllModelsExhausted(errors)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		bridge = self._primary_bridge()
		if bridge is None:
			raise AllModelsExhausted([(t, "backend unavailable") for t in self._targets])
		return bridge.continue_conversation(text, conversation_id=conversation_id, previous_response_len=previous_response_len, timeout=timeout)

	def health_check(self) -> bool:
		"""True if any target in the cascade is reachable."""
		for t in self._targets:
			try:
				if self._build(t.backend).health_check():
					return True
			except Exception:
				continue
		return False
