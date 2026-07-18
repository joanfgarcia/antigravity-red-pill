"""
Red Pill Foundation — EventBus
==============================
Lightweight, thread-safe event bus for decoupled signaling between
Foundation and Enterprise/Community layers.

DESIGN PRINCIPLES
-----------------
- Foundation emits; Enterprise/Community subscribe. Never the reverse.
- Sync listeners run inline (same thread as the emitter).
- Async listeners are fire-and-forget (asyncio.create_task if a loop exists,
	else skipped silently — CLI callers don't need async).
- Broken listeners are isolated: one bad handler cannot crash the emitter.
- Zero hard dependencies on Enterprise: the bus lives 100% in Foundation.

USAGE (Foundation — emitting)
------------------------------
	from red_pill.events import get_event_bus, MemoryAddedEvent
	get_event_bus().emit(MemoryAddedEvent(collection="work_memories", engram_id=uid))

USAGE (Enterprise — subscribing, in their own __init__ or boot hook)
----------------------------------------------------------------------
	from red_pill.events import get_event_bus, SleepCompletedEvent

	def on_sleep(event: SleepCompletedEvent) -> None:
		cerberus_client.upload(event.summary)

	get_event_bus().subscribe(SleepCompletedEvent, on_sleep)

AVAILABLE EVENTS (Foundation-emitted)
--------------------------------------
	MemoryAddedEvent        — after a new engram is stored
	SleepCompletedEvent     — after a sleep/consolidation cycle
	CollectionCreatedEvent  — after StorageEngine creates a new Qdrant collection
	CliCommandDispatchedEvent — after main() resolves the CLI command
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

# Event Base & Typed Events


@dataclasses.dataclass
class RedPillEvent:
	"""All Foundation events inherit from this class."""

	timestamp: float = dataclasses.field(default_factory=time.time)


@dataclasses.dataclass
class MemoryAddedEvent(RedPillEvent):
	"""Fired after MemoryManager.add_memory() stores a new engram."""

	collection: str = ""
	engram_id: str = ""
	importance: float = 1.0
	emotion: str = "neutral"
	color: str = "gray"


@dataclasses.dataclass
class SleepCompletedEvent(RedPillEvent):
	"""Fired after perform_sleep_cycle() finishes consolidation."""

	collection: str = ""
	processed_count: int = 0
	mode: str = "lazy"  # "lazy" | "deep"


@dataclasses.dataclass
class RecallEvent(RedPillEvent):
	"""Fired after MemoryManager.search_and_reinforce() returns — memory utility metric."""

	collection: str = ""
	caller: str = "unknown"
	query_len: int = 0
	hits: int = 0
	top_score: Optional[float] = None


@dataclasses.dataclass
class CollectionCreatedEvent(RedPillEvent):
	"""Fired after StorageEngine creates a new Qdrant collection."""

	collection_name: str = ""


@dataclasses.dataclass
class AxonWeaveEvent(RedPillEvent):
	"""Fired after an AxonWeaverPhase cycle (ADR-AXON-001 P6) — includes the gate's
	rejection stats so AXON_GATE can be tuned from data during the shadow rollout."""

	candidates_evaluated: int = 0
	axons_woven: int = 0
	axons_repaired: int = 0
	axons_pruned: int = 0
	rejected_by_gate: int = 0
	w_accepted_avg: Optional[float] = None
	w_rejected_avg: Optional[float] = None
	effective_runs: int = 0


@dataclasses.dataclass
class AxonTraversalEvent(RedPillEvent):
	"""Fired when the evocative cascade traverses cross axons at query time."""

	source_collection: str = ""
	target_collection: str = ""
	traversed: int = 0
	orphans: int = 0


@dataclasses.dataclass
class SoulCreatedEvent(RedPillEvent):
	"""Fired after 'redpill export' creates a new local backup zip."""

	zip_path: str = ""


@dataclasses.dataclass
class CliCommandDispatchedEvent(RedPillEvent):
	"""Fired in main() after argparse resolves the command."""

	command: str = ""
	subcommand: Optional[str] = None


# EventBus

E = TypeVar("E", bound=RedPillEvent)
ListenerFn = Callable[[Any], Any]  # (event) -> None | Coroutine


class EventBus:
	"""
	Thread-safe synchronous + async event bus.

	Listeners are keyed by event class (exact type, no inheritance walk).
	If you want to catch all events, subscribe to RedPillEvent (explicit).
	"""

	def __init__(self) -> None:
		self._lock = threading.Lock()
		self._listeners: Dict[Type[RedPillEvent], List[ListenerFn]] = {}

	def subscribe(self, event_type: Type[E], listener: ListenerFn) -> None:
		"""Register a listener for the given event type.

		Args:
			event_type: The exact event class to listen for.
			listener:   Callable(event) -> None.  May be a coroutine function.
		"""
		with self._lock:
			if event_type not in self._listeners:
				self._listeners[event_type] = []
			self._listeners[event_type].append(listener)
		logger.debug(f"[EventBus] Subscribed {listener!r} to {event_type.__name__}")

	def unsubscribe(self, event_type: Type[E], listener: ListenerFn) -> bool:
		"""Remove a specific listener. Returns True if it was found and removed."""
		with self._lock:
			bucket = self._listeners.get(event_type, [])
			try:
				bucket.remove(listener)
				return True
			except ValueError:
				return False

	def emit(self, event: RedPillEvent) -> None:
		"""
		Fire an event synchronously.

		Sync listeners run inline (blocking).
		Async listeners use asyncio.create_task() if a running loop exists;
		otherwise they are silently skipped (safe for CLI / non-async contexts).
		"""
		with self._lock:
			listeners = list(self._listeners.get(type(event), []))

		for listener in listeners:
			try:
				result = listener(event)
				# If the listener returned a coroutine, schedule it if possible
				if asyncio.iscoroutine(result):
					try:
						loop = asyncio.get_running_loop()
						loop.create_task(result)  # type: ignore[unused-awaitable]
					except RuntimeError:
						# No running loop (CLI context) — close the coroutine to avoid warnings
						result.close()
			except Exception as e:
				logger.warning(f"[EventBus] Listener {listener!r} raised on {type(event).__name__}: {e}")

	def clear(self, event_type: Optional[Type[RedPillEvent]] = None) -> None:
		"""Remove all listeners for a given type, or all listeners if None."""
		with self._lock:
			if event_type is None:
				self._listeners.clear()
			else:
				self._listeners.pop(event_type, None)

	def listener_count(self, event_type: Type[RedPillEvent]) -> int:
		"""Return the number of listeners registered for a given event type."""
		with self._lock:
			return len(self._listeners.get(event_type, []))


# Singleton accessor

_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
	"""Return the process-wide EventBus singleton."""
	global _bus
	if _bus is None:
		with _bus_lock:
			if _bus is None:
				_bus = EventBus()
	return _bus


def reset_event_bus() -> None:
	"""Replace the singleton with a fresh EventBus. Intended for tests only."""
	global _bus
	with _bus_lock:
		_bus = EventBus()
