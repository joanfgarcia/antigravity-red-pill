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
1. Plugin discovery runs exactly once per process (`_discovered`), whatever was
	registered before: an explicit registration never hides a plugin.
2. Factories are tried in registration order; the first one returning a
	strategy wins. A factory returns None to decline (its backend is not in use).
3. No factory applies → `NullPulseStrategy`.

A factory receives a `PulseContext` (what the worker built) and returns a
strategy or None.
"""

import importlib
import logging
import os
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
	from red_pill.core.agent_worker import IDEWorker
	from red_pill.swarm.bridges import BridgeCapabilities

logger = logging.getLogger(__name__)

_PULSE_MODULE = "pulse"


@dataclass(frozen=True)
class PulseContext:
	"""What a strategy factory may inspect to decide whether its backend is in use.

	`capabilities` are those of the conversational (Telegram) bridge, or None if
	no bridge could be built."""

	bridge_minion: object = None
	capabilities: Optional["BridgeCapabilities"] = None


# Factories registered by backend plugins at import time.
_STRATEGY_FACTORIES: List[Callable[[PulseContext], Optional["PulseStrategy"]]] = []
# Plugin discovery runs once per process, independently of prior registrations.
_discovered = False


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


def _emit_strategy_fallback_signal(module: str, error: BaseException) -> None:
	"""Pain signal for a plugin whose pulse module exists but failed to import:
	its backend-specific pulse silently stops otherwise. Deduplicated by name
	(`has_signal`), so the per-minute oneshot worker does not spam it."""
	plugin = module.split(".")[-2] if "." in module else module
	name = f"pulse_strategy_fallback_{plugin}"
	try:
		from red_pill.memory import MemoryManager

		mm = MemoryManager()
		if mm.has_signal(name):
			return
		mm.inject_signal(
			name=name,
			intensity=6.0,
			signal_type="pain",
			source="IDEWorker",
			originator="core.pulse_strategy._discover_plugin_strategies",
			criticality="WARNING",
			message=f"La estrategia de pulse `{module}` no carga ({type(error).__name__}: {str(error)[:300]}); su backend queda sin pulse específico.",
		)
	except Exception as e:
		logger.warning("[pulse] failed to emit strategy fallback signal for %s: %s", module, e)


def _has_pulse_module(importer: object, pkg_name: str) -> bool:
	"""True if the plugin package ships a `pulse` module, checked on disk so that
	discovery does not import every plugin package (and its dependencies) on each
	oneshot run. A non-filesystem importer cannot be inspected: let the import decide."""
	base = getattr(importer, "path", None)
	if not isinstance(base, str):
		return True
	return any(m.name == _PULSE_MODULE for m in pkgutil.iter_modules([os.path.join(base, pkg_name)]))


def _discover_plugin_strategies() -> None:
	"""Import `red_pill.plugins.<pkg>.pulse` modules so they self-register.
	Mirrors the daemon's pkgutil plugin discovery. Never raises.

	A plugin without a pulse module is skipped quietly. A pulse module that
	exists but fails to import (itself or a transitive dependency) is an error:
	logged and reported with a deduplicated pain signal, never swallowed."""
	global _discovered
	_discovered = True
	try:
		import red_pill.plugins as plugins_pkg
	except Exception as e:  # pragma: no cover - defensive
		logger.error("[pulse] plugins package unavailable: %s", e)
		return

	for importer, pkg_name, is_pkg in pkgutil.iter_modules(plugins_pkg.__path__):
		if pkg_name.startswith("_") or not is_pkg or not _has_pulse_module(importer, pkg_name):
			continue
		candidate = f"{plugins_pkg.__name__}.{pkg_name}.{_PULSE_MODULE}"
		try:
			importlib.import_module(candidate)
		except ModuleNotFoundError as e:
			if e.name == candidate:
				logger.debug("[pulse] %s has no pulse strategy", pkg_name)
				continue
			logger.error("[pulse] strategy module %s failed to import (missing %s): its backend pulse is disabled", candidate, e.name)
			_emit_strategy_fallback_signal(candidate, e)
		except Exception as e:
			logger.error("[pulse] strategy module %s failed to import: %s — its backend pulse is disabled", candidate, e)
			_emit_strategy_fallback_signal(candidate, e)


def build_pulse_strategy(context: PulseContext) -> PulseStrategy:
	"""Resolve the active pulse strategy without naming any backend.

	Order: plugin discovery (once) → registered factories → NullPulseStrategy.
	This is the ONLY selection point; the core stays agnostic because it never
	references a concrete provider here."""
	if not _discovered:
		_discover_plugin_strategies()

	for factory in list(_STRATEGY_FACTORIES):
		try:
			strategy = factory(context)
		except Exception as e:
			logger.error("[pulse] strategy factory %r failed: %s", factory, e)
			continue
		if strategy is not None:
			return strategy

	return NullPulseStrategy()
