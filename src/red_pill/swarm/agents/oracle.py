from typing import Any, Dict

from red_pill.swarm.base import Minion


class OracleMinion(Minion):
	"""
	Context Research & Memory Retrieval Agent.
	Integrates with the Bünker for deep recall.
	"""

	name: str = "Oracle-01"
	specialization: str = "Knowledge Synthesis & RAG Research"

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""
		Search the memory substrate and synthesize context.
		"""
		from red_pill.memory import MemoryManager
		manager = MemoryManager()

		self.log(f"Investigando contexto para: {task}")

		# Simple RAG search across work and social for broad context
		results = []
		for collection in ["work_memories", "social_memories"]:
			hits = manager.search_and_reinforce(collection, task, limit=3)
			results.extend([h.payload["content"] for h in hits])

		synthesis = "\n".join(results) if results else "No se encontró contexto previo relevante."

		return {
			"status": "success",
			"synthesis": synthesis,
			"source_count": len(results)
		}
