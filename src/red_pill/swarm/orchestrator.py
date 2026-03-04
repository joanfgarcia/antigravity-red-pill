import asyncio
import time
from typing import List

from red_pill.swarm.base import Minion, SwarmResult


class GruOrchestrator:
	"""
	The Sovereign Orchestrator (Gru).
	Manages the deployment and collection of specialized Minions.
	"""

	def __init__(self):
		self.active_minions: List[Minion] = []

	def is_local_ready(self) -> bool:
		"""Check if local SLM infrastructure is available."""
		import os

		ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
		model_dir = os.path.join(ia_dir, "models")
		if not os.path.exists(model_dir):
			return False
		return any(f.endswith(".gguf") for f in os.listdir(model_dir))

	async def deploy_swarm(self, task: str, minions: List[Minion], **kwargs) -> List[SwarmResult]:
		"""Deploy a set of minions in parallel and collect results."""
		tasks = [self._run_minion(m, task, **kwargs) for m in minions]
		results = await asyncio.gather(*tasks)

		# SAS: Sovereign Alert System integration (v5.6.2)
		self._trigger_sas(task, results)

		return results

	def _trigger_sas(self, task: str, results: List[SwarmResult]) -> None:
		"""Record memory and notify user of swarm completion."""
		from red_pill.memory import MemoryManager
		from red_pill.utils.observer import notify_user

		success_count = len([r for r in results if r.status == "success"])
		message = f"Swarm Task Complete: {task}. {success_count}/{len(results)} minions succeeded."

		# 1. Sensory Signal (User) - Silent by default per Operator directive
		notify_user(title="Sovereign Swarm", message=message, sound=False)

		# 2. Memory Signal (Agent) - For Turn-Zero recovery
		try:
			manager = MemoryManager()
			manager.add_memory(
				collection="directive_memories",
				text=f"SWARM EVENT: {message}\nResults: {results}",
				importance=1.0,
				metadata={"type": "swarm_event", "task": task, "timestamp": time.time(), "results": [r.model_dump() for r in results]}
			)
		except Exception as e:
			print(f"SAS Memory Hook failed: {e}")

	async def _run_minion(self, minion: Minion, task: str, **kwargs) -> SwarmResult:
		start = time.time()
		try:
			result = await minion.execute(task, **kwargs)
			return SwarmResult(minion_id=minion.id, status="success", duration=round(time.time() - start, 3), result=result)
		except Exception as e:
			return SwarmResult(minion_id=minion.id, status="failed", duration=round(time.time() - start, 3), result={}, error=str(e))
