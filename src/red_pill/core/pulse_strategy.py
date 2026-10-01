"""PulseStrategy — the backend-specific part of the IDEWorker pulse loop.

The `IDEWorker` owns what is **generic**: the inbox → bridge → outbox cycle,
AWAKENINGs, Telegram routing, Samantha. It does NOT own what is
**backend-specific**: the Antigravity legacy gRPC polling, the `agy` autonomous
operations, or trajectory extraction.

That backend-specific work is delegated to a `PulseStrategy` (ARCH-001 paso B).
Two implementations exist:

- ``NullPulseStrategy`` (here): a no-op for backends with nothing to poll
  (e.g. opencode/claude/local) — the generic pulse is enough.
- ``AntigravityPulseStrategy`` (``red_pill.plugins.antigravity_ide.pulse``): the
  legacy gRPC polling + `agy` autonomous operations + trajectory access.

`IDEWorker.run_once()` orchestrates the generic steps and then calls
``strategy.pulse(worker)`` once per tick. Selecting the strategy is the only
place the worker looks at the backend type.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
	from red_pill.core.agent_worker import IDEWorker


@runtime_checkable
class PulseStrategy(Protocol):
	"""Backend-specific behaviour injected into the generic worker pulse."""

	def pulse(self, worker: "IDEWorker") -> None:
		"""Run one backend-specific tick. Must never raise (the worker wraps it,
		but a well-behaved strategy contains its own errors per step)."""
		...


class NullPulseStrategy:
	"""No-op strategy: the backend has nothing backend-specific to poll."""

	def pulse(self, worker: "IDEWorker") -> None:
		return None
