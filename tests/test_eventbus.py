"""
Tests for Phase 4 EventBus — Foundation event signaling.
Covers: subscribe, emit, unsubscribe, isolation, async listeners,
and all 4 Foundation event types.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

from red_pill.events import (
	CliCommandDispatchedEvent,
	CollectionCreatedEvent,
	MemoryAddedEvent,
	RedPillEvent,
	SleepCompletedEvent,
	get_event_bus,
	reset_event_bus,
)


@pytest.fixture(autouse=True)
def fresh_bus():
	"""Each test gets a clean EventBus singleton."""
	reset_event_bus()
	yield
	reset_event_bus()


# Core EventBus mechanics


class TestEventBusCore:
	def test_subscribe_and_emit(self):
		"""A subscribed listener receives the emitted event."""
		bus = get_event_bus()
		received = []
		bus.subscribe(MemoryAddedEvent, lambda e: received.append(e))
		event = MemoryAddedEvent(collection="work_memories", engram_id="abc")
		bus.emit(event)
		assert received == [event]

	def test_multiple_listeners_same_event(self):
		"""All listeners for an event type are called."""
		bus = get_event_bus()
		calls = []
		bus.subscribe(MemoryAddedEvent, lambda e: calls.append("L1"))
		bus.subscribe(MemoryAddedEvent, lambda e: calls.append("L2"))
		bus.emit(MemoryAddedEvent())
		assert calls == ["L1", "L2"]

	def test_listeners_isolated_by_type(self):
		"""Listeners for type A do not fire when type B is emitted."""
		bus = get_event_bus()
		memory_calls = []
		sleep_calls = []
		bus.subscribe(MemoryAddedEvent, lambda e: memory_calls.append(e))
		bus.subscribe(SleepCompletedEvent, lambda e: sleep_calls.append(e))
		bus.emit(SleepCompletedEvent(collection="work_memories", processed_count=5))
		assert memory_calls == []
		assert len(sleep_calls) == 1

	def test_broken_listener_does_not_propagate(self):
		"""A listener that raises does not prevent subsequent listeners from running."""
		bus = get_event_bus()
		good = MagicMock()

		def bad(e):
			raise RuntimeError("I am broken")

		bus.subscribe(MemoryAddedEvent, bad)
		bus.subscribe(MemoryAddedEvent, good)
		bus.emit(MemoryAddedEvent())
		good.assert_called_once()

	def test_unsubscribe(self):
		"""unsubscribe() removes a listener; it no longer fires."""
		bus = get_event_bus()
		cb = MagicMock()
		bus.subscribe(MemoryAddedEvent, cb)
		bus.unsubscribe(MemoryAddedEvent, cb)
		bus.emit(MemoryAddedEvent())
		cb.assert_not_called()

	def test_unsubscribe_unknown_returns_false(self):
		"""unsubscribe() returns False when listener is not registered."""
		bus = get_event_bus()
		cb = MagicMock()
		assert bus.unsubscribe(MemoryAddedEvent, cb) is False

	def test_clear_all(self):
		"""clear() with no args removes all listeners for all event types."""
		bus = get_event_bus()
		cb = MagicMock()
		bus.subscribe(MemoryAddedEvent, cb)
		bus.subscribe(SleepCompletedEvent, cb)
		bus.clear()
		bus.emit(MemoryAddedEvent())
		bus.emit(SleepCompletedEvent())
		cb.assert_not_called()

	def test_clear_specific_type(self):
		"""clear(EventType) removes listeners only for that type."""
		bus = get_event_bus()
		m_cb = MagicMock()
		s_cb = MagicMock()
		bus.subscribe(MemoryAddedEvent, m_cb)
		bus.subscribe(SleepCompletedEvent, s_cb)
		bus.clear(MemoryAddedEvent)
		bus.emit(MemoryAddedEvent())
		bus.emit(SleepCompletedEvent())
		m_cb.assert_not_called()
		s_cb.assert_called_once()

	def test_listener_count(self):
		"""listener_count() returns the correct number of registered listeners."""
		bus = get_event_bus()
		assert bus.listener_count(MemoryAddedEvent) == 0
		bus.subscribe(MemoryAddedEvent, lambda e: None)
		bus.subscribe(MemoryAddedEvent, lambda e: None)
		assert bus.listener_count(MemoryAddedEvent) == 2

	def test_thread_safety(self):
		"""EventBus does not deadlock when called from multiple threads."""
		bus = get_event_bus()
		counts = []
		bus.subscribe(MemoryAddedEvent, lambda e: counts.append(1))

		def emitter():
			for _ in range(50):
				bus.emit(MemoryAddedEvent())

		threads = [threading.Thread(target=emitter) for _ in range(5)]
		for t in threads:
			t.start()
		for t in threads:
			t.join()
		assert len(counts) == 250


# Async listener support


class TestAsyncListeners:
	def test_async_listener_scheduled_with_running_loop(self):
		"""Async listener is scheduled via create_task when a loop is running."""
		bus = get_event_bus()
		results = []

		async def async_handler(event: MemoryAddedEvent):
			results.append(event.engram_id)

		bus.subscribe(MemoryAddedEvent, async_handler)

		async def run():
			bus.emit(MemoryAddedEvent(engram_id="async-test"))
			await asyncio.sleep(0)  # yield to allow the task to run

		asyncio.run(run())
		assert "async-test" in results

	def test_async_listener_closed_without_loop(self):
		"""Async listener coroutine is closed (no warning) in non-async context."""
		bus = get_event_bus()
		called = []

		async def async_handler(event):
			called.append(event)

		bus.subscribe(MemoryAddedEvent, async_handler)
		bus.emit(MemoryAddedEvent())  # No running loop — should not raise


# Typed event dataclasses


class TestEventDataclasses:
	def test_memory_added_event_fields(self):
		e = MemoryAddedEvent(collection="work_memories", engram_id="id1", importance=5.0, emotion="joy", color="orange")
		assert e.collection == "work_memories"
		assert e.engram_id == "id1"
		assert e.importance == 5.0
		assert e.emotion == "joy"
		assert e.color == "orange"
		assert isinstance(e.timestamp, float)

	def test_sleep_completed_event_fields(self):
		e = SleepCompletedEvent(collection="interaction_memories", processed_count=42, mode="deep")
		assert e.processed_count == 42
		assert e.mode == "deep"

	def test_collection_created_event_fields(self):
		e = CollectionCreatedEvent(collection_name="new_memories")
		assert e.collection_name == "new_memories"

	def test_cli_command_dispatched_event_fields(self):
		e = CliCommandDispatchedEvent(command="sleep", subcommand=None)
		assert e.command == "sleep"
		assert e.subcommand is None

	def test_red_pill_event_timestamp_defaults(self):
		before = time.time()
		e = RedPillEvent()
		after = time.time()
		assert before <= e.timestamp <= after


# Singleton


class TestSingleton:
	def test_same_instance(self):
		"""get_event_bus() always returns the same object."""
		assert get_event_bus() is get_event_bus()

	def test_reset_creates_new_instance(self):
		"""reset_event_bus() replaces the singleton with a fresh one."""
		bus1 = get_event_bus()
		reset_event_bus()
		bus2 = get_event_bus()
		assert bus1 is not bus2
