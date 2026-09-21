"""Hilo de Ariadna — nivel MICRO (single-writer D3/D8, I2).

El nivel MACRO (cadena de hubs de sesión por fecha) ya lo teje `thread_weave_migrate`.
Aquí se teje el nivel MICRO: se encadenan los engramas de cada sesión por su
**orden de refine** (`refine_ref`, no `created_at` — que está para la fecha real),
en un campo PROPIO (`prev_member`/`next_member`, I2) para no colisionar con el
significado de `associations` (axones).

El nivel transversal (`cross_refs`) son axones: los teje `weave_cross_axons`.

Todo tras `SW_THREAD_ENABLED`.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import red_pill.config as cfg

logger = logging.getLogger(__name__)

_REFINE_NUM = re.compile(r"/(\d+)-")


def member_sort_key(payload: Dict[str, Any]) -> Tuple[int, str]:
	"""Clave de orden del miembro: prefijo numérico de `refine_ref` (o 0)."""
	ref = str(payload.get("refine_ref") or "")
	m = _REFINE_NUM.search(ref)
	num = int(m.group(1)) if m else 0
	if num == 0:
		m2 = re.search(r"(\d+)", ref)
		num = int(m2.group(1)) if m2 else 0
	return (num, ref)


def _group_members(points: List[Tuple[Any, Dict[str, Any]]]) -> Dict[str, List[Tuple[Any, Dict[str, Any]]]]:
	groups: Dict[str, List[Tuple[Any, Dict[str, Any]]]] = {}
	for pid, payload in points:
		payload = payload or {}
		if payload.get("node_type") == "synthesis_hub" or payload.get("lazarus_phase") == "synthesis_hub":
			continue
		sid = str(payload.get("session_id") or "")
		if not sid:
			continue
		groups.setdefault(sid, []).append((pid, payload))
	return groups


def weave_member_threads(
	memory_manager: Any,
	collections: Tuple[str, ...] = ("work_memories", "social_memories"),
) -> Dict[str, Any]:
	"""Teje el micro-hilo (prev/next_member) por sesión, ordenado por refine."""
	if not bool(getattr(cfg, "SW_THREAD_ENABLED", False)):
		return {"sessions": 0, "links": 0, "enabled": False}

	stats = {"sessions": 0, "links": 0, "enabled": True}
	for collection in collections:
		try:
			if not memory_manager.client.collection_exists(collection):
				continue
			points: List[Tuple[Any, Dict[str, Any]]] = []
			offset = None
			while True:
				batch, offset = memory_manager.client.scroll(collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
				points.extend((p.id, p.payload) for p in batch)
				if offset is None:
					break
			for session_id, members in _group_members(points).items():
				if len(members) < 2:
					continue
				ordered = sorted(members, key=lambda m: member_sort_key(m[1]))
				stats["sessions"] += 1
				n = len(ordered)
				for i, (pid, _pl) in enumerate(ordered):
					pad: Dict[str, Any] = {"member_index": i, "member_count": n}
					if i > 0:
						pad["prev_member"] = str(ordered[i - 1][0])
						stats["links"] += 1
					if i < n - 1:
						pad["next_member"] = str(ordered[i + 1][0])
						stats["links"] += 1
					try:
						memory_manager.client.set_payload(collection_name=collection, payload=pad, points=[pid])
					except Exception as e:
						logger.warning(f"[THREAD] set_payload falló en {collection}:{pid}: {e}")
		except Exception as e:
			logger.error(f"[THREAD] fallo tejiendo micro-hilo en {collection}: {e}")
	return stats


def follow_member_thread(memory_manager: Any, collection: str, start_id: str, direction: str = "next", max_steps: int = 50) -> List[str]:
	"""Camina el micro-hilo desde `start_id` (siguiente/anterior). Devuelve ids."""
	field = "next_member" if direction == "next" else "prev_member"
	chain: List[str] = []
	cur = str(start_id)
	for _ in range(max_steps):
		try:
			res = memory_manager.client.retrieve(collection_name=collection, ids=[cur])
		except Exception:
			break
		if not res:
			break
		nxt: Optional[str] = (res[0].payload or {}).get(field)
		if not nxt:
			break
		chain.append(str(nxt))
		cur = str(nxt)
	return chain
