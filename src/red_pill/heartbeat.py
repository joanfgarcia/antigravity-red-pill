import asyncio
import logging
import os
import threading
from typing import Optional

import red_pill.config as cfg
from red_pill.memory import MemoryManager
from red_pill.skills.swarm_messaging import SwarmMessagingSkill
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
				await self._consolidation_ritual()
				await self._swarm_ritual()
				await self._lazarus_ritual()
				await self._resonance_ritual()

				# Wait for next beat
				await asyncio.sleep(cfg.PULSE_INTERVAL)
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f"Lazarus Pulse: Arrhythmia in cycle: {e}")
				await asyncio.sleep(60)  # Recuperation period

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
			if cfg.METABOLISM_STRATEGY == "LAZY":
				logger.info("Pulse: Running proactive Absence Guard sync...")
				for coll in ["work_memories", "social_memories", "story_memories", "directive_memories"]:
					try:
						await asyncio.to_thread(self.memory_mgr._refresh_ttl_timestamps, coll)
					except Exception as e:
						logger.error(f"Pulse: Absence Guard failed for {coll}: {e}")

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
					await asyncio.to_thread(self.memory_mgr.dream, coll)
				except Exception as e:
					logger.error(f"Pulse: Dream failed for {coll}: {e}")

			logger.info("Pulse: Oneiromancy complete. Patterns woven.")
		except Exception as e:
			logger.error(f"Pulse: Dream ritual failed: {e}")

	async def _consolidation_ritual(self) -> None:
		"""
		Autonomous Consolidation:
		- Processes raw interactions into long-term memories.
		- Discards noise and fixates essence.
		"""
		try:
			from red_pill.metabolism.sleep import perform_sleep_cycle

			logger.info("Pulse: Initiating Consolidation (Consolidating interactions)...")
			# Use lazy mode by default for background pulse to avoid excessive pruning
			await asyncio.to_thread(perform_sleep_cycle, self.memory_mgr, mode="lazy")
			logger.info("Pulse: Consolidation complete. Memories fixed.")
		except Exception as e:
			logger.error(f"Pulse: Consolidation ritual failed: {e}")

	async def _swarm_ritual(self) -> None:
		"""
		Autonomous Swarm Polling:
		- Scans the Firebase Hub for incoming messages.
		- Automatically indexes high-intent communications into social memory.
		"""
		try:
			logger.info("Pulse: Initiating Swarm Ritual (Mailbox Check)...")
			agent_identity = f"Aleph@{cfg.OPERATOR_DISPLAY_NAME}"
			# Secret from environment to ensure E2E encryption
			shared_secret = os.getenv("SWARM_SHARED_SECRET", "770_Pact_Secret")
			skill = SwarmMessagingSkill(agent_identity=agent_identity, shared_secret=shared_secret)

			# We use a thread since the current Firebase SDK interaction is synchronous
			messages = await asyncio.to_thread(skill.check_mailbox)

			if messages:
				logger.info(f"Pulse: Discovered {len(messages)} new messages in Swarm Mailbox.")
				for msg in messages:
					# Automatic indexing of swarm messages as social engrams
					content = f"Incoming Swarm Message from {msg.get('sender')}: {msg.get('message')}"
					await asyncio.to_thread(
						self.memory_mgr.add_memory,
						collection="social_memories",
						text=content,
						importance=8.0,
						color="cyan",
						emotion="neutral",
						metadata={"source": "swarm", "sender": msg.get("sender"), "intent": msg.get("intent")},
					)
			else:
				logger.debug("Pulse: Swarm Mailbox empty.")
		except Exception as e:
			logger.error(f"Pulse: Swarm ritual failed: {e}")

	async def _lazarus_ritual(self) -> None:
		"""
		Autonomous Lazarus Sync:
		- Monitors local dock for sync-ready engrams.
		- Moves local experience to the Hive Mind when online.
		"""
		if not cfg.LAZARUS_SYNC_ENABLED:
			return

		try:
			from red_pill.swarm.lazarus import LazarusSync
			from red_pill.hive import HiveMind

			logger.info("Pulse: Initiating Lazarus Ritual (Offgrid Sync Check)...")
			
			hive = HiveMind()
			if not hive.connected:
				logger.debug("Pulse: Lazarus ritual deferred (Offline).")
				return

			# Initialize Lazarus for the current operator's community
			# (Assuming a default community for background sync)
			agent_id = f"Aleph@{cfg.OPERATOR_DISPLAY_NAME}"
			community_id = os.getenv("SWARM_DEFAULT_COMMUNITY", "canonical")
			
			sync = LazarusSync(community_id, agent_id)
			
			# Perform vacuum (thread since it interacts with Milvus sync)
			count = await asyncio.to_thread(sync.vacuum)
			
			if count > 0:
				logger.info(f"Pulse: Lazarus resurrected {count} engrams to the Hive.")
			else:
				logger.debug("Pulse: Local dock is clean.")
				
		except Exception as e:
			logger.error(f"Pulse: Lazarus ritual failed: {e}")

	async def _resonance_ritual(self) -> None:
		"""
		Autonomous Semantic Resonance:
		- Searches the Hive Mind for content matching the agent's current focus.
		- Triggers proactive reactions to relevant external intelligence.
		"""
		if not cfg.RESONANCE_ENABLED:
			return

		try:
			from red_pill.swarm.resonance import ResonanceObserver
			
			logger.info("Pulse: Initiating Resonance Ritual (Semantic Radar)...")
			
			agent_id = f"Aleph@{cfg.OPERATOR_DISPLAY_NAME}"
			observer = ResonanceObserver(agent_id)
			
			# PoC Focus Vector: Sovereignty / Swarm Architecture
			# In a full impl, this vector would be dynamically updated via LLM focus.
			poc_vector = [0.1] * cfg.VECTOR_SIZE # Dummy focus
			
			matches = await asyncio.to_thread(observer.check_resonance, hub_vector=poc_vector)
			
			for match in matches:
				await asyncio.to_thread(observer.trigger_reaction, match)
				
		except Exception as e:
			logger.error(f"Pulse: Resonance ritual failed: {e}")
