"""MEM-011 · aislamiento por rol — solo la raíz compite en el recall primario.

D-SH-01/I-08: las partes existen, navegan y se erosionan, pero **no** son
candidatas del primario. El marcado `hubbed=True, hub_id=<raíz>` ya las excluye
del camino semántico (filtro estructural por `hub_id`); estos tests cubren las dos
rutas que no pasaban por ese filtro:

- la pata keyword de hubs, que escaneaba todos los `synthesis_hub` (y contaba las
  partes en el IDF, triplicando los documentos con los mismos términos);
- la densidad de hubs, que contaba el árbol entero como una sola unidad.
"""

from __future__ import annotations

import types
from typing import Any, Dict, List, Tuple

from red_pill.metabolism.sw_observability import compute_sw_health


def _condition_matches(payload: Dict[str, Any], cond: Any) -> bool:
	key = getattr(cond, "key", "")
	match = getattr(cond, "match", None)
	if match is None:
		return False
	values = getattr(match, "any", None)
	if values is not None:
		return payload.get(key) in values
	return payload.get(key) == getattr(match, "value", None)


def _filter_matches(payload: Dict[str, Any], flt: Any) -> bool:
	should = getattr(flt, "should", None) or []
	must_not = getattr(flt, "must_not", None) or []
	if should and not any(_condition_matches(payload, c) for c in should):
		return False
	if any(_condition_matches(payload, c) for c in must_not):
		return False
	return True


class _FakeQdrant:
	"""Scroll/retrieve mínimos que respetan `should` y `must_not`."""

	def __init__(self, docs: List[Tuple[str, Dict[str, Any]]]) -> None:
		self.docs = docs

	def collection_exists(self, collection_name: str) -> bool:
		return bool(self.docs)

	def scroll(self, collection_name: str, **kwargs: Any):
		flt = kwargs.get("scroll_filter")
		batch = [types.SimpleNamespace(id=pid, payload=payload) for pid, payload in self.docs if flt is None or _filter_matches(payload, flt)]
		limit = int(kwargs.get("limit") or len(batch))
		return batch[:limit], None

	def retrieve(self, collection_name: str, ids: List[str], **kwargs: Any):
		wanted = {str(i) for i in ids}
		return [types.SimpleNamespace(id=pid, payload=payload, vector=None) for pid, payload in self.docs if str(pid) in wanted]


def _manager(client: Any, **overrides: Any) -> Any:
	from red_pill.memory import MemoryManager

	manager = object.__new__(MemoryManager)
	manager.client = client
	defaults: Dict[str, Any] = {
		"SW_HUB_KEYWORD_ENABLED": True,
		"MEMORY_HUB_KEYWORD_MAX_HUBS": 500,
	}
	defaults.update(overrides)
	manager.cfg = types.SimpleNamespace(**defaults)
	return manager


def _hub(pid: str, **extra: Any) -> Tuple[str, Dict[str, Any]]:
	payload: Dict[str, Any] = {
		"node_type": "synthesis_hub",
		"lazarus_phase": "synthesis_hub",
		"hub_title": "Polaroids y memoria",
		"hub_terms": ["polaroid", "memoria", "empaquetado"],
		"content": "Polaroids y memoria: el empaquetado por partes.",
	}
	payload.update(extra)
	return pid, payload


def test_la_pata_keyword_no_devuelve_partes():
	docs = [
		_hub("root-1"),
		_hub("part-1", hub_role="part", hub_id="root-1", part_key="0001-0040"),
		_hub("legacy-sin-rol"),
	]
	manager = _manager(_FakeQdrant(docs))

	ranked = manager._hub_keyword_hits("polaroid memoria empaquetado", "work_memories", limit=10)

	ids = [pid for pid, _ in ranked]
	assert "part-1" not in ids, "una parte no es raíz: no compite en el primario (D-SH-01/I-08)"
	assert set(ids) == {"root-1", "legacy-sin-rol"}, "la raíz y el hub legado sin `hub_role` sí compiten"


def test_la_densidad_de_hubs_cuenta_raices_no_el_arbol():
	data = {
		"work_memories": [
			("r1", {"node_type": "synthesis_hub", "lazarus_phase": "synthesis_hub"}),
			("p1", {"node_type": "synthesis_hub", "lazarus_phase": "synthesis_hub", "hub_role": "part", "hub_id": "r1"}),
			("p2", {"node_type": "synthesis_hub", "lazarus_phase": "synthesis_hub", "hub_role": "part", "hub_id": "r1"}),
			("c1", {"node_type": "memento_engram", "origin": "memento", "session_id": "s", "hubbed": True, "hub_id": "r1"}),
			("c2", {"node_type": "memento_engram", "origin": "memento", "session_id": "s"}),
			("c3", {"node_type": "memento_engram", "origin": "memento", "session_id": "s"}),
			("c4", {"node_type": "memento_engram", "origin": "memento", "session_id": "s"}),
		],
	}
	health = compute_sw_health(types.SimpleNamespace(client=_FakeQdrant(data["work_memories"])))
	wm = health["collections"]["work_memories"]

	assert wm["hubs"] == 3, "el total de nodos del árbol sigue siendo visible"
	assert wm["hubs_root"] == 1
	assert wm["hubs_part"] == 2
	assert wm["hub_ratio_pct"] == 25.0, "la densidad se mide sobre raíces (1 de 4 engrams), no sobre el árbol entero"
