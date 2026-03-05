import asyncio
import logging
import time
from typing import List

from red_pill.memory import MemoryManager
from red_pill.swarm.base import Minion, SwarmResult
from red_pill.utils.observer import notify_user
from red_pill.utils.specs_adapter import SpecsAdapter

logger = logging.getLogger(__name__)


class GruOrchestrator:
	"""
	The Sovereign Orchestrator (Gru).
	Manages the deployment and collection of specialized Minions.
	Integrated with specs.md (v5.6.2) and the Sovereign Alert System (SAS).
	"""

	def __init__(self):
		import os

		self.active_minions: List[Minion] = []
		self.workspace_root = os.getcwd()
		self.specs = SpecsAdapter(self.workspace_root)
		self.memory = MemoryManager()

	def is_local_ready(self) -> bool:
		"""Check if local SLM infrastructure is available."""
		import os

		ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
		model_dir = os.path.join(ia_dir, "models")
		if not os.path.exists(model_dir):
			return False
		return any(f.endswith(".gguf") for f in os.listdir(model_dir))

	async def deploy_swarm(self, task: str, minions: List[Minion], **kwargs) -> List[SwarmResult]:
		"""Deploys a swarm of specialized agents with Sync-Shield protection."""

		# 1. Sync-Shield: Automatic Ghost Collection Refresh (Sound of Silence philosophy)
		if self.specs.is_specs_aware():
			current_hash = self.specs.get_specs_hash()
			bunker_hash = self.memory.get_sync_hash("specs_memories")

			if current_hash != bunker_hash:
				logger.info("[SYNC-SHIELD] Disk/Bünker drift detected. Auto-syncing Ghost Collection...")
				self.memory.sync_specs(self.workspace_root)
				self.memory.set_sync_hash("specs_memories", current_hash)
				logger.info("[SYNC-SHIELD] Synchronization complete.")

		# 2. Spec-Aware Context Injection
		specs_prefix = ""
		flow = self.specs.detect_flow()
		if flow == "fire":
			intents = self.specs.get_fire_intents()
			if intents:
				specs_prefix = f"[SPECS: FIRE INTENTS]\n{intents}\n---\n"
		elif flow == "simple":
			tasks = self.specs.get_simple_tasks()
			if tasks:
				specs_prefix = f"[SPECS: SIMPLE TASKS]\n{tasks}\n---\n"

		# 3. Enrich the task with specs context
		enriched_task = f"{specs_prefix}{task}" if specs_prefix else task

		# 4. Deploy Minions
		logger.info(f"Deploying swarm to execute: {task[:100]}...")
		tasks_parallel = [self._run_minion(m, enriched_task, **kwargs) for m in minions]
		results = await asyncio.gather(*tasks_parallel)

		# 5. SAS: Sovereign Alert System integration
		self._trigger_sas(task, results)

		return results

	def _trigger_sas(self, task: str, results: List[SwarmResult]) -> None:
		"""Record memory and notify user of swarm completion."""
		success_count = len([r for r in results if r.status == "success"])
		message = f"Swarm Task Complete: {task}. {success_count}/{len(results)} minions succeeded."

		# Sensory Signal (User) - Silent by default per Operator directive
		notify_user(title="Sovereign Swarm", message=message, sound=False)

		# Memory Signal (Agent) - For Turn-Zero recovery
		try:
			self.memory.add_memory(
				collection="directive_memories",
				text=f"SWARM EVENT: {message}\nResults: {results}",
				importance=1.0,
				metadata={"type": "swarm_event", "task": task, "timestamp": time.time(), "results": [r.model_dump() for r in results]},
			)
		except Exception as e:
			logger.error(f"SAS Memory Hook failed: {e}")

	async def _run_minion(self, minion: Minion, task: str, **kwargs) -> SwarmResult:
		start = time.time()
		try:
			result = await minion.execute(task, **kwargs)
			return SwarmResult(minion_id=minion.id, status="success", duration=round(time.time() - start, 3), result=result)
		except Exception as e:
			return SwarmResult(minion_id=minion.id, status="failed", duration=round(time.time() - start, 3), result={}, error=str(e))
