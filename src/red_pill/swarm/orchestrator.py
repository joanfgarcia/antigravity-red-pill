import asyncio
import time
from typing import List, Dict, Any
from red_pill.swarm.base import Minion, SwarmResult

class GruOrchestrator:
	"""
	The Sovereign Orchestrator (Gru).
	Manages the deployment and collection of specialized Minions.
	"""

	def __init__(self):
		self.active_minions: List[Minion] = []

	async def deploy_swarm(self, task: str, minions: List[Minion], **kwargs) -> List[SwarmResult]:
		"""Deploy a set of minions in parallel and collect results."""
		start_time = time.time()
		tasks = [self._run_minion(m, task, **kwargs) for m in minions]
		results = await asyncio.gather(*tasks)
		return results

	async def _run_minion(self, minion: Minion, task: str, **kwargs) -> SwarmResult:
		start = time.time()
		try:
			result = await minion.execute(task, **kwargs)
			return SwarmResult(
				minion_id=minion.id,
				status="success",
				duration=round(time.time() - start, 3),
				result=result
			)
		except Exception as e:
			return SwarmResult(
				minion_id=minion.id,
				status="failed",
				duration=round(time.time() - start, 3),
				result={},
				error=str(e)
			)
