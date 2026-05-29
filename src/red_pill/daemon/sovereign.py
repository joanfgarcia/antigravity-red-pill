"""
SovereignDaemon — The ONE daemon to rule them all.

Single-process, plugin-based control plane.  Monitors and dispatches.
Never executes heavy work — that belongs to timer-triggered one-shots.

Architecture:
  ┌─────────────────────────────────────────────┐
  │  SovereignDaemon (PID 1 of Red Pill)        │
  │  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
  │  │telemetry │ │  echo    │ │  vitals  │    │
  │  │ 30s/10s  │ │ 60s/15s  │ │ 120s/15s │    │
  │  └──────────┘ └──────────┘ └──────────┘    │
  │  ┌──────────┐ ┌──────────────────────┐      │
  │  │  swarm   │ │  timer_watchdog      │      │
  │  │ 300s/5s  │ │  60s/5s              │      │
  │  └──────────┘ └──────────────────────┘      │
  │  [Optional] SyntaxGuard thread (inotify)    │
  └─────────────────────────────────────────────┘

"Perfection is achieved, not when there is nothing more to add,
 but when there is nothing left to take away."
"""

import asyncio
import importlib
import logging
import os
import pkgutil
import signal
import socket
import time
from typing import List, Optional

from red_pill.daemon.plugin import DaemonPlugin

logger = logging.getLogger("red_pill.daemon")

# Main loop tick interval (seconds). Plugins have their own intervals.
_LOOP_TICK_S = 1.0


def _sd_notify(state: str) -> None:
	"""Send a notification to systemd (Type=notify / WatchdogSec). No-op if not under systemd."""
	addr = os.environ.get("NOTIFY_SOCKET")
	if not addr:
		return
	try:
		sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
		if addr[0] == "@":
			addr = "\0" + addr[1:]
		sock.sendto(state.encode(), addr)
		sock.close()
	except Exception:
		pass


class SovereignDaemon:
	"""The unified control plane daemon.

	Discovers, loads, and supervises DaemonPlugin instances.
	Each plugin ticks at its own interval, with a hard timeout.
	If a plugin blocks or crashes, the daemon logs pain and continues.
	"""

	def __init__(self) -> None:
		self.plugins: List[DaemonPlugin] = []
		self.running = True
		self._loop: Optional[asyncio.AbstractEventLoop] = None

	def _discover_plugins(self) -> None:
		"""Auto-discover DaemonPlugin subclasses from red_pill.daemon.plugins package."""
		import red_pill.daemon.plugins as plugins_pkg

		for _importer, mod_name, _ispkg in pkgutil.iter_modules(plugins_pkg.__path__):
			if mod_name.startswith("_"):
				continue
			try:
				module = importlib.import_module(f"red_pill.daemon.plugins.{mod_name}")
				# Find all DaemonPlugin subclasses in the module
				for attr_name in dir(module):
					attr = getattr(module, attr_name)
					if (
						isinstance(attr, type)
						and issubclass(attr, DaemonPlugin)
						and attr is not DaemonPlugin
					):
						plugin = attr()
						if plugin.enabled:
							self.plugins.append(plugin)
							logger.info(f"[SOVEREIGN] Loaded plugin: {plugin}")
						else:
							logger.info(f"[SOVEREIGN] Skipped disabled plugin: {plugin.name}")
			except Exception as e:
				logger.error(f"[SOVEREIGN] Failed to load plugin module '{mod_name}': {e}")

	async def _tick_plugin(self, plugin: DaemonPlugin) -> None:
		"""Execute a single plugin tick with hard timeout protection."""
		try:
			await asyncio.wait_for(plugin.tick(), timeout=plugin.timeout_s)
		except asyncio.TimeoutError:
			logger.error(
				f"[SOVEREIGN] Plugin '{plugin.name}' TIMEOUT after {plugin.timeout_s}s. "
				f"Skipping. Pain signal injected."
			)
			self._inject_timeout_pain(plugin)
		except Exception as e:
			logger.error(f"[SOVEREIGN] Plugin '{plugin.name}' error: {e}")

	def _inject_timeout_pain(self, plugin: DaemonPlugin) -> None:
		"""Inject a pain signal when a plugin exceeds its timeout."""
		try:
			from red_pill.memory import MemoryManager

			mm = MemoryManager()
			signal_name = f"daemon_plugin_{plugin.name}_timeout"
			if not mm.has_signal(signal_name):
				mm.inject_signal(
					name=signal_name,
					intensity=6.0,
					signal_type="pain",
					source="SovereignDaemon",
					originator=f"daemon.sovereign._tick_plugin({plugin.name})",
					criticality="WARNING",
				)
		except Exception as e:
			logger.warning(f"[SOVEREIGN] Failed to inject timeout pain for '{plugin.name}': {e}")

	async def _main_loop(self) -> None:
		"""The main supervisor loop. Ticks plugins at their intervals."""
		# Start all plugins
		for plugin in self.plugins:
			try:
				await asyncio.wait_for(plugin.on_start(), timeout=10.0)
				logger.info(f"[SOVEREIGN] Plugin '{plugin.name}' started.")
			except Exception as e:
				logger.error(f"[SOVEREIGN] Plugin '{plugin.name}' on_start() failed: {e}")

		_sd_notify("READY=1")
		logger.info(
			f"[SOVEREIGN] Daemon ready. {len(self.plugins)} plugins loaded. "
			f"PID: {os.getpid()}"
		)

		while self.running:
			now = time.monotonic()

			# Watchdog heartbeat
			_sd_notify("WATCHDOG=1")

			# Tick each plugin if its interval has elapsed
			for plugin in self.plugins:
				if plugin.should_tick(now):
					await self._tick_plugin(plugin)
					plugin.record_tick(now)

			await asyncio.sleep(_LOOP_TICK_S)

		# Graceful shutdown
		for plugin in self.plugins:
			try:
				await asyncio.wait_for(plugin.on_stop(), timeout=5.0)
			except Exception as e:
				logger.warning(f"[SOVEREIGN] Plugin '{plugin.name}' on_stop() failed: {e}")

		logger.info("[SOVEREIGN] All plugins stopped. Daemon exiting.")

	def _shutdown(self) -> None:
		"""Signal handler for graceful shutdown."""
		logger.info("[SOVEREIGN] Shutdown signal received.")
		self.running = False

	def run(self, oneshot: bool = False) -> None:
		"""Main entry point. Discovers plugins and runs the event loop.

		Args:
			oneshot: If True, tick all plugins once and exit (for testing).
		"""
		logging.basicConfig(
			level=logging.INFO,
			format="%(asctime)s [%(levelname)s] %(message)s",
		)

		self._discover_plugins()

		if not self.plugins:
			logger.warning("[SOVEREIGN] No plugins discovered. Nothing to do.")
			return

		if oneshot:
			asyncio.run(self._run_oneshot())
			return

		# Full daemon mode
		self._loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self._loop)

		# Register signal handlers
		for sig in (signal.SIGINT, signal.SIGTERM):
			self._loop.add_signal_handler(sig, self._shutdown)

		try:
			self._loop.run_until_complete(self._main_loop())
		finally:
			self._loop.close()
			logger.info("[SOVEREIGN] Flatline. Goodbye.")

	async def _run_oneshot(self) -> None:
		"""Tick all plugins once and exit. Used for testing."""
		for plugin in self.plugins:
			try:
				await asyncio.wait_for(plugin.on_start(), timeout=10.0)
			except Exception as e:
				logger.error(f"[SOVEREIGN] Plugin '{plugin.name}' on_start() failed: {e}")

		logger.info(f"[SOVEREIGN] Oneshot: ticking {len(self.plugins)} plugins...")
		for plugin in self.plugins:
			logger.info(f"[SOVEREIGN] Ticking '{plugin.name}'...")
			await self._tick_plugin(plugin)

		for plugin in self.plugins:
			try:
				await asyncio.wait_for(plugin.on_stop(), timeout=5.0)
			except Exception:
				pass

		logger.info("[SOVEREIGN] Oneshot complete.")
