"""El recall por hoja debe respetar `limit` (Oracle 2026-11-26).

El enrutado por hoja busca con holgura (`limit * 6`) para agregar cada hoja a su
raíz, pero devolvía todas las raíces encontradas: con `limit=3` llegaban 7-10
fragmentos al dossier (y al RAG). El contrato del llamante es `limit`.
"""

from qdrant_client.http import models as qm

import red_pill.config as cfg
from red_pill.memory import MemoryManager


def _point(i: int) -> qm.ScoredPoint:
	return qm.ScoredPoint(
		id=f"00000000-0000-0000-0000-{i:012d}",
		version=0,
		score=1.0 - i / 100.0,
		payload={"content": f"nota {i}", "immune": True},
		vector=None,
	)


def test_leaf_routing_respeta_el_limit(monkeypatch):
	manager = MemoryManager()
	monkeypatch.setattr(cfg, "SW_RECALL_LEAF_ROUTING_ENABLED", True)
	monkeypatch.setattr(manager, "_get_vector", lambda _q: [0.1] * 384)
	monkeypatch.setattr(manager, "_route_by_leaf", lambda *a, **k: [_point(i) for i in range(7)])
	monkeypatch.setattr(manager, "_reinforce_points", lambda *a, **k: [])

	hits = manager._search_and_reinforce_impl("work_memories", "q", limit=3)

	assert len(hits) == 3
	assert [h.payload["content"] for h in hits] == ["nota 0", "nota 1", "nota 2"]


def test_leaf_routing_no_recorta_si_hay_menos(monkeypatch):
	manager = MemoryManager()
	monkeypatch.setattr(cfg, "SW_RECALL_LEAF_ROUTING_ENABLED", True)
	monkeypatch.setattr(manager, "_get_vector", lambda _q: [0.1] * 384)
	monkeypatch.setattr(manager, "_route_by_leaf", lambda *a, **k: [_point(0), _point(1)])
	monkeypatch.setattr(manager, "_reinforce_points", lambda *a, **k: [])

	hits = manager._search_and_reinforce_impl("work_memories", "q", limit=3)

	assert len(hits) == 2
