"""PulseStrategy — the backend-specific part of the worker pulse loop.

The `IDEWorker` owns what is **generic**: the inbox → bridge → outbox cycle,
AWAKENINGs, routing, the Telegram session janitor and the Samantha signal. It
does NOT own what is **backend-specific** (polling a particular IDE, autonomous
ops for a particular CLI, trajectory extraction). That work is delegated to a
`PulseStrategy` (ARCH-001).

The core is **provider-agnostic**: it never imports or names a specific
backend/plugin. Instead, backends register a strategy *factory* via
`register_pulse_strategy(factory)` when their plugin module is imported, and the
core discovers them through the same `pkgutil` plugin convention used by the
daemon (`red_pill.daemon.sovereign`). If no factory applies, the core falls back
to `NullPulseStrategy` — the generic pulse keeps running either way.

Resolution (`build_pulse_strategy`):
1. If nothing is registered, auto-discover `red_pill.plugins.<pkg>.pulse` modules.
2. Factories are tried in registration order; the first one returning a
	strategy wins. A factory returns None to decline (its backend is not in use).
3. No factory applies → `NullPulseStrategy`.

A factory receives a `PulseContext` (what the worker built) and returns a
strategy or None.
"""

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
	from red_pill.core.agent_worker import IDEWorker
	from red_pill.swarm.bridges import BridgeCapabilities

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PulseContext:
	"""What a strategy factory may inspect to decide whether its backend is in use.

	`capabilities` are those of the conversational (Telegram) bridge, or None if
	no bridge could be built."""

	bridge_minion: object = None
	capabilities: Optional["BridgeCapabilities"] = None


# Factories registered by backend plugins at import time.
_STRATEGY_FACTORIES: List[Callable[[PulseContext], Optional["PulseStrategy"]]] = []


@runtime_checkable
class PulseStrategy(Protocol):
	"""Backend-specific behaviour injected into the generic worker pulse."""

	def pulse(self, worker: "IDEWorker") -> None:
		"""Run one backend-specific tick. Must never raise (the worker wraps it,
		but a well-behaved strategy contains its own errors per step)."""
		...

	def allows_core_housekeeping(self, worker: "IDEWorker") -> bool:
		"""Whether the core runs its generic housekeeping (Telegram session
		janitor + Samantha signal) after this tick. A strategy returns False only
		for a backend path that historically owned the tick without it."""
		...


class NullPulseStrategy:
	"""No-op strategy: the backend has nothing backend-specific to poll."""

	def pulse(self, worker: "IDEWorker") -> None:
		return None

	def allows_core_housekeeping(self, worker: "IDEWorker") -> bool:
		return True


def register_pulse_strategy(factory: Callable[[PulseContext], Optional[PulseStrategy]]) -> None:
	"""Register a backend strategy factory. Called by backend plugins at import
	time. The factory receives a `PulseContext` and returns a strategy (or None
	to decline). Idempotent: re-registering the same factory is a no-op."""
	if factory not in _STRATEGY_FACTORIES:
		_STRATEGY_FACTORIES.append(factory)


def _discover_plugin_strategies() -> None:
	"""Import `red_pill.plugins.<pkg>.pulse` modules so they self-register.
	Mirrors the daemon's pkgutil plugin discovery. Never raises."""
	try:
		import red_pill.plugins as plugins_pkg
	except Exception as e:  # pragma: no cover - defensive
		logger.debug("[pulse] plugins package unavailable: %s", e)
		return

	for _importer, mod_name, is_pkg in pkgutil.iter_modules(plugins_pkg.__path__):
		if mod_name.startswith("_"):
			continue
		candidate = f"red_pill.plugins.{mod_name}.pulse"
		try:
			importlib.import_module(candidate)
		except ModuleNotFoundError:
			continue  # this plugin has no pulse strategy — fine
		except Exception as e:  # pragma: no cover - defensive
			logger.warning("[pulse] failed to load strategy module %s: %s", candidate, e)
		_ = is_pkg  # silence linters; kept for clarity of the iter API


def build_pulse_strategy(context: PulseContext) -> PulseStrategy:
	"""Resolve the active pulse strategy without naming any backend.

	Order: registered factories → plugin discovery → NullPulseStrategy. This is
	the ONLY selection point; the core stays agnostic because it never references
	a concrete provider here."""
	if not _STRATEGY_FACTORIES:
		_discover_plugin_strategies()

	for factory in _STRATEGY_FACTORIES:
		try:
			strategy = factory(context)
		except Exception as e:
			logger.error("[pulse] strategy factory %r failed: %s", factory, e)
			continue
		if strategy is not None:
			return strategy

	return NullPulseStrategy()
