import logging

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin

logger = logging.getLogger(__name__)


class RagEnrichmentPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "RAG Enrichment (Memory Sidecar)"

	@property
	def timeout(self) -> float:
		return 1.5  # Give it 1.5 seconds to do semantic search

	@property
	def is_enabled(self) -> bool:
		return getattr(cfg, "INTERCEPTOR_ENABLED", False) and getattr(cfg, "INTERCEPTOR_RAG_ENABLED", True)

	async def execute(self, prompt: str) -> str:
		try:
			# Use to_thread since memory manager is heavily synchronous
			import asyncio

			def _search():
				from red_pill.memory import MemoryManager

				manager = MemoryManager()
				results = []
				for collection in ["directive_memories", "work_memories", "social_memories"]:
					try:
						hits = manager.search_and_reinforce(collection, prompt, limit=2)
						results.extend(
							[
								str(h.payload.get("content", ""))
								for h in hits
								if h.payload
								and h.payload.get("content")
								and getattr(h, "score", 0.0) >= getattr(cfg, "SEMANTIC_INTENT_THRESHOLD", 0.0)
							]
						)
					except Exception as e:
						logger.warning(f"RAG search failed for {collection}: {e}")
				return results

			results = await asyncio.to_thread(_search)

			unique_results = []
			for r in results:
				if r not in unique_results:
					unique_results.append(r)

			if not unique_results:
				return ""

			background = "\n---\n".join(unique_results)

			# Log removed to prevent overwriting the Assistant's real conversational response in work_memories.

			return f"[CONTEXTO CORTEX ENCONTRADO PARA ESTA TAREA]\n{background}"

		except Exception as e:
			logger.error(f"RAG Enrichment crashed: {e}")
			return ""
