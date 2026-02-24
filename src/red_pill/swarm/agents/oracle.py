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
		import os
		from red_pill.memory import MemoryManager
		from red_pill.swarm.agents.edge_engine import EdgeEngine
		
		manager = MemoryManager()

		self.log(f"Investigando contexto para: {task}")

		# Simple RAG search across work and social for broad context
		results = []
		for collection in ["work_memories", "social_memories"]:
			hits = manager.search_and_reinforce(collection, task, limit=3)
			results.extend([h.payload["content"] for h in hits])

		background = "\n---\n".join(results) if results else ""
		
		# Edge Synthesis Logic
		ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
		model_dir = os.path.join(ia_dir, "models")
		model_file = next((os.path.join(model_dir, f) for f in os.listdir(model_dir) if f.endswith(".gguf")), None) if os.path.exists(model_dir) else None

		if model_file:
			self.log(f"🔮 Sintetizando con SLM local: {os.path.basename(model_file)}")
			engine = EdgeEngine(model_path=model_file)
			synthesis = engine.synthesize(background, task)
		else:
			self.log("⚠️ No SLM found. Usando concatenación de fragmentos.")
			synthesis = background if background else "No se encontró contexto previo relevante."

		return {
			"status": "success",
			"synthesis": synthesis,
			"source_count": len(results)
		}

