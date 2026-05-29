"""
DaemonPlugin — Abstract base class for Sovereign Daemon plugins.

"La perfección se alcanza no cuando no hay nada más que añadir,
sino cuando no queda nada por quitar."
— Antoine de Saint-Exupéry

Rules:
1. tick() is MONITOR-ONLY. No execution, no processing, no blocking.
2. Each tick() has a hard timeout_s. Exceed it → pain signal + skip.
3. The daemon NEVER dies because a plugin misbehaves.
"""

from abc import ABC, abstractmethod


class DaemonPlugin(ABC):
	_last_tick: float = 0.0

	"""Base class for all Sovereign Daemon plugins.

	Plugins are lightweight monitor/control units that:
	- Read system state (telemetry, health checks, inbox counts)
	- Dispatch signals (pain/evaporate) to Qdrant
	- Write status panels (LED markdown, state files)
	- NEVER execute heavy tasks (those go to timer one-shots)

	The daemon supervisor calls tick() at interval_s frequency,
	wrapped in asyncio.wait_for(timeout_s). If tick() blocks or
	raises, the daemon logs the error, injects a pain signal,
	and moves on to the next plugin.
	"""

	@property
	@abstractmethod
	def name(self) -> str:
		"""Unique short name for this plugin (e.g. 'telemetry', 'echo')."""
		...

	@property
	def interval_s(self) -> float:
		"""Seconds between tick() calls. Default: 60."""
		return 60.0

	@property
	def timeout_s(self) -> float:
		"""Hard timeout for a single tick(). Default: 5s.
		If exceeded, the daemon kills the tick, injects pain, and continues."""
		return 5.0

	@property
	def enabled(self) -> bool:
		"""Override to conditionally disable a plugin based on config."""
		return True

	async def on_start(self) -> None:
		"""Called once when the daemon boots. Override for initialization."""

	async def on_stop(self) -> None:
		"""Called once on graceful shutdown. Override for cleanup."""

	@abstractmethod
	async def tick(self) -> None:
		"""The plugin's main work unit. Called every interval_s seconds.

		MUST be non-blocking and complete within timeout_s.
		Read state, check health, dispatch signals. Never execute.
		"""
		...

	def should_tick(self, now: float) -> bool:
		"""Returns True if enough time has elapsed since the last tick."""
		elapsed = now - self._last_tick
		return elapsed >= self.interval_s

	def record_tick(self, now: float) -> None:
		"""Records the timestamp of the last tick."""
		self._last_tick = now

	def __init_subclass__(cls, **kwargs: object) -> None:
		super().__init_subclass__(**kwargs)
		cls._last_tick = 0.0

	def __repr__(self) -> str:
		return f"<{self.__class__.__name__} name={self.name} interval={self.interval_s}s timeout={self.timeout_s}s>"
