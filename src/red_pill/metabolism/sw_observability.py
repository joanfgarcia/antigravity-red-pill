"""Observabilidad del single-writer (D26).

Señales de salud para detectar regresiones silenciosas (el fallo "verde con 0
digerido"): cobertura de hubs, frescura del semáforo de situación y cobertura de
afinidad. Solo lectura; no modifica nada.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_IS_HUB = lambda pl: pl.get("lazarus_phase") == "synthesis_hub" or pl.get("node_type") == "synthesis_hub"  # noqa: E731
_IS_CONTENT = lambda pl: pl.get("node_type") == "memento_engram" or (pl.get("origin") == "memento" and not _IS_HUB(pl))  # noqa: E731


def _scroll_all(client: Any, collection: str) -> List[Any]:
	out: List[Any] = []
	offset = None
	while True:
		batch, offset = client.scroll(collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
		out.extend(batch)
		if offset is None:
			break
	return out


def compute_sw_health(memory_manager: Any, collections: Tuple[str, ...] = ("work_memories", "social_memories")) -> Dict[str, Any]:
	"""Métricas de cobertura/frescura del single-writer (puro salvo scrolls)."""
	client = memory_manager.client
	now = time.time()
	out: Dict[str, Any] = {"collections": {}, "solera_age_h": None, "affinity_coverage": None}

	for c in collections:
		try:
			if not client.collection_exists(c):
				continue
			pts = _scroll_all(client, c)
			content = sum(1 for p in pts if _IS_CONTENT(p.payload or {}))
			hubs = sum(1 for p in pts if _IS_HUB(p.payload or {}))
			hubbed = sum(1 for p in pts if (p.payload or {}).get("hubbed"))
			out["collections"][c] = {
				"total": len(pts),
				"content": content,
				"hubs": hubs,
				"hubbed_members": hubbed,
				"hub_coverage_pct": round(100 * hubs / max(1, content), 1),
			}
		except Exception as e:
			logger.warning(f"[SW-OBS] {c}: {e}")

	try:
		if client.collection_exists("situation_memories"):
			pts = _scroll_all(client, "situation_memories")
			ages = [now - float((p.payload or {}).get("updated_at", now)) for p in pts]
			out["solera_age_h"] = round(min(ages) / 3600, 1) if ages else None
	except Exception:
		pass

	try:
		if client.collection_exists("interaction_memories"):
			pts = _scroll_all(client, "interaction_memories")
			if pts:
				with_aff = sum(1 for p in pts if ((p.payload or {}).get("metadata") or {}).get("affinity"))
				out["affinity_coverage"] = round(with_aff / len(pts), 3)
	except Exception:
		pass

	return out
