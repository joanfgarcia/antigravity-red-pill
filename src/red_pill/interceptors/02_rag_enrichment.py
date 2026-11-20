import logging

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.recall_abstention import passes_injection, similarity

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
				# I-06/C-09: la postura de INYECCIÓN aplica el suelo al presentar.
				# El umbral efectivo es el más alto de suelo e intención; las
				# directivas y los inmunes pasan siempre (I-03).
				floor = float(getattr(cfg, "SW_RECALL_ABSTENTION_FLOOR", 0.38) or 0.0)
				intent = float(getattr(cfg, "SEMANTIC_INTENT_THRESHOLD", 0.0) or 0.0)
				for collection in ["directive_memories", "work_memories", "social_memories"]:
					try:
						hits = manager.search_and_reinforce(collection, prompt, limit=2, caller="interceptor_02")
						for h in hits:
							payload = h.payload or {}
							content = payload.get("content")
							if not content:
								continue
							immune = bool(payload.get("immune")) or collection == "directive_memories"
							if passes_injection(similarity(h), floor=floor, intent_threshold=intent, immune=immune):
								results.append(str(content))
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
