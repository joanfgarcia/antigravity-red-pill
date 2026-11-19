"""MEM-012 · F2 — la postura de INYECCIÓN aplica el suelo (C-09, I-03, I-06).

El interceptor 02 es el RAG por turno: lo que devuelve entra al contexto. Estos
tests fijan que un hit por debajo del suelo **no** llega ahí, que el umbral de
intención manda si es más alto, y que inmunes/directivas no cambian (I-03).
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch


def _hit(point_id: str, score: float, content: str, **payload: Any) -> SimpleNamespace:
	return SimpleNamespace(id=point_id, score=score, payload={"content": content, **payload})


def test_el_interceptor_no_inyecta_lo_que_no_alcanza_el_suelo():
	module = importlib.import_module("red_pill.interceptors.02_rag_enrichment")
	plugin = module.RagEnrichmentPlugin()

	hits: Dict[str, List[Any]] = {
		"directive_memories": [_hit("d", 0.60, "contenido-directiva", immune=True)],
		"work_memories": [_hit("bajo", 0.30, "contenido-bajo"), _hit("alto", 0.60, "contenido-alto")],
		"social_memories": [],
	}

	class _Manager:
		def __init__(self, *_a: Any, **_k: Any) -> None:
			pass

		def search_and_reinforce(self, collection: str, prompt: str, limit: int, caller: str) -> List[Any]:
			return hits[collection]

	with patch("red_pill.memory.MemoryManager", _Manager):
		text = asyncio.run(plugin.execute("consulta cualquiera"))

	assert "contenido-alto" in text
	assert "contenido-bajo" not in text, "C-09: el contexto inyectado nunca ve la banda baja"
	assert "contenido-directiva" in text, "I-03: las directivas conservan su comportamiento (umbral de intención)"
