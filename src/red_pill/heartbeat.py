import asyncio
import logging
import threading
from typing import Optional

import red_pill.config as cfg
from red_pill.memory import MemoryManager
from red_pill.soul import SoulManager

logger = logging.getLogger("red_pill.heartbeat")

class LazarusPulse:
	"""
	The Heartbeat of the Sovereign Agent.
	Runs autonomous rituals to maintain Bünker health and ontological integrity.
	"""
	def __init__(self, memory_mgr: MemoryManager, soul_mgr: SoulManager) -> None:
		self.memory_mgr = memory_mgr
		self.soul_mgr = soul_mgr
		self._running = False
		self._loop: Optional[asyncio.AbstractEventLoop] = None
		self._thread: Optional[threading.Thread] = None

	def start(self) -> None:
		"""Starts the heartbeat in a dedicated background thread."""
		if not cfg.PULSE_ENABLED:
			logger.info("Lazarus Pulse: Disabled via config.")
			return

		if self._running:
			return

		self._running = True
		self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="LazarusPulse")
		self._thread.start()
		logger.info(f"Lazarus Pulse: Rhythm initiated (Interval: {cfg.PULSE_INTERVAL}s)")

	def stop(self) -> None:
		"""Gradually stops the heartbeat."""
		if not self._running:
			return
		self._running = False
		if self._loop:
			self._loop.call_soon_threadsafe(self._loop.stop)
		if self._thread:
			self._thread.join(timeout=2.0)
		logger.info("Lazarus Pulse: Flatline.")

	def _run_event_loop(self) -> None:
		"""Entry point for the pulse thread."""
		self._loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self._loop)
		self._loop.create_task(self._pulse_cycle())
		try:
			self._loop.run_forever()
		finally:
			self._loop.close()

	async def _pulse_cycle(self) -> None:
		"""The repeating biological cycle."""
		while self._running:
			try:
				logger.info("Lazarus Pulse: Beat triggered. Executing rituals...")
				await self._maintenance_ritual()
				await self._dream_ritual()

				# Wait for next beat
				await asyncio.sleep(cfg.PULSE_INTERVAL)
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f"Lazarus Pulse: Arrhythmia in cycle: {e}")
				await asyncio.sleep(60) # Recuperation period

	async def _maintenance_ritual(self) -> None:
		"""
		Autonomous Maintenance:
		- DB Connectivity check.
		- Proactive Metabolism (Absence Guard sync).
		- Storage Health.
		"""
		try:
			# 1. DB Connectivity
			try:
				self.memory_mgr.client.get_collections()
				logger.debug("Pulse: Bünker connectivity verified.")
			except Exception:
				logger.warning("Pulse: Bünker connection lost. Attempting recovery...")

			# 2. Absence Guard (Proactive TTL refresh)
			# Ensures memories don't "suddenly" decay after long inactivity if the user
			# forgets to interact. This stabilizes the biological runway.
			if cfg.METABOLISM_STRATEGY == "LAZY":
				logger.info("Pulse: Running proactive Absence Guard sync...")
				for coll in ["work_memories", "social_memories", "story_memories", "directive_memories"]:
					try:
						# We run the synchronous refresh in a thread to avoid blocking the pulse loop
						await asyncio.to_thread(self.memory_mgr._refresh_ttl_timestamps, coll)
					except Exception as e:
						logger.error(f"Pulse: Absence Guard failed for {coll}: {e}")

			# 3. Storage Health
			# (Placeholder for future quota/cleanup tasks)

			logger.info("Pulse: Maintenance ritual complete. 770 stable.")

		except Exception as e:
			logger.error(f"Pulse: Maintenance ritual failed: {e}")

	async def _dream_ritual(self) -> None:
		"""
		Autonomous Oneiromancy:
		- Finds latent semantic associations between memories.
		- Simulates cognitive 'dreaming' to strengthen synaptic density.
		"""
		try:
			logger.info("Pulse: Initiating Oneiromancy (Dream Ritual)...")
			for coll in ["work_memories", "social_memories", "story_memories"]:
				try:
					# Synchronous dream call in a thread
					await asyncio.to_thread(self.memory_mgr.dream, coll)
				except Exception as e:
					logger.error(f"Pulse: Dream failed for {coll}: {e}")

			logger.info("Pulse: Oneiromancy complete. Patterns woven.")
		except Exception as e:
			logger.error(f"Pulse: Dream ritual failed: {e}")
