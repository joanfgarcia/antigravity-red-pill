import os
from typing import Any, Dict

from red_pill.memory import MemoryManager
from red_pill.swarm.agents.edge_engine import EdgeEngine
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

		manager = MemoryManager()

		self.log(f"Investigando contexto para: {task}")

		# Simple RAG search across work and social for broad context
		results = []
		for collection in ["work_memories", "social_memories"]:
			hits = manager.search_and_reinforce(collection, task, limit=3)
			results.extend([h.payload["content"] for h in hits])

		background = "\n---\n".join(results) if results else ""

		# Edge Synthesis Logic
		engine = EdgeEngine()

		if engine.llm:
			self.log(f"🔮 Sintetizando con {os.path.basename(engine.model_path) if engine.model_path else 'No model path'}")
			synthesis = engine.synthesize(background, task)
		else:
			self.log("⚠️ No local LLM found. Usando concatenación de fragmentos.")
			synthesis = background if background else "No se encontró contexto previo relevante."

		return {"status": "success", "synthesis": synthesis, "source_count": len(results)}
