"""Regresión: el rescate por keyword debe alcanzar miembros hubbed (D14).

Bug 2026-10-07: `_rerank_hybrid_mmr` aplicaba TODAS las exclusiones
estructurales al rescate por keyword, incluida `hubbed=True`. Como los
engramas consolidados están hubbed, cualquier recall por nombre propio
(IDF altísimo) descartaba sus hits y caía al top semántico genérico.
"""

import types

from qdrant_client import models

from red_pill.memento import hybrid as hy
from red_pill.memory import MemoryManager


class _Rec:
    def __init__(self, pid, payload, vector):
        self.id = pid
        self.payload = payload
        self.vector = vector


class _Client:
    def retrieve(self, collection_name, ids, with_payload, with_vectors):
        return [_Rec(i, {"hubbed": True, "reinforcement_score": 8.0, "content": "tribu"}, [1.0, 0.0]) for i in ids]


def test_keyword_rescue_reaches_hubbed_member(monkeypatch):
    monkeypatch.setattr(hy, "memento_keyword_hits", lambda *a, **k: [("pt1", 20.0)])
    m = MemoryManager.__new__(MemoryManager)
    m.client = _Client()
    m.cfg = types.SimpleNamespace(MEMORY_RECALL_MMR_ENABLED=False, MEMORY_RECALL_MMR_LAMBDA=0.7)
    exclusions = [models.FieldCondition(key="hubbed", match=models.MatchValue(value=True))]
    out = m._rerank_hybrid_mmr("work_memories", "Sofi", [1.0, 0.0], [], 3, True, False, False, exclusions)
    assert [str(h.id) for h in out] == ["pt1"]
