"""PulseStrategy — the backend-specific part of the worker pulse loop.

The `IDEWorker` owns what is **generic**: the inbox → bridge → outbox cycle,
AWAKENINGs, routing, Samantha. It does NOT own what is **backend-specific**
(polling a particular IDE, autonomous ops for a particular CLI, trajectory
extraction). That work is delegated to a `PulseStrategy` (ARCH-001).

The core is **provider-agnostic**: it never imports or names a specific
backend/plugin. Instead, backends register their strategy via
`register_pulse_strategy(cls)` when their plugin module is imported, and the
core discovers them through the same `pkgutil` plugin convention used by the
daemon (`red_pill.daemon.sovereign`). If no strategy is registered and none can
be discovered, the core falls back to `NullPulseStrategy`.

Discovery order (first match wins):
1. Explicitly registered strategies (`register_pulse_strategy`).
2. Auto-discovery of `red_pill.plugins.<pkg>.pulse` modules exposing a
   `PulseStrategy` implementation.

A strategy constructor must accept a single positional arg: the minion bridge
(or None).
"""

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING, Callable, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
	from red_pill.core.agent_worker import IDEWorker

logger = logging.getLogger(__name__)

# Factories registered by backend plugins at import time. A factory takes the
# minion bridge and returns a strategy instance (or None if it does not apply).
_STRATEGY_FACTORIES: List[Callable[[object], Optional["PulseStrategy"]]] = []


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


def register_pulse_strategy(factory: Callable[[object], Optional[PulseStrategy]]) -> None:
	"""Register a backend strategy factory. Called by backend plugins at import
	time. The factory receives the minion bridge and returns a strategy (or None
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


def build_pulse_strategy(bridge_minion: object) -> PulseStrategy:
	"""Resolve the active pulse strategy without naming any backend.

	Order: registered factories → plugin discovery → NullPulseStrategy. This is
	the ONLY selection point; the core stays agnostic because it never references
	a concrete provider here."""
	if not _STRATEGY_FACTORIES:
		_discover_plugin_strategies()

	for factory in _STRATEGY_FACTORIES:
		try:
			strategy = factory(bridge_minion)
		except Exception as e:
			logger.error("[pulse] strategy factory %r failed: %s", factory, e)
			continue
		if strategy is not None:
			return strategy

	return NullPulseStrategy()
