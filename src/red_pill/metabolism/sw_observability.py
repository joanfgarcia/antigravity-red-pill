"""Observabilidad del single-writer (D26).

Señales de salud para detectar regresiones silenciosas (el fallo "verde con 0
digerido"): cobertura de hubs, frescura del semáforo de situación y cobertura de
afinidad. Solo lectura; no modifica nada.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from red_pill.metabolism.hub_synthesis import is_content_node, is_groupable, is_hub_node

logger = logging.getLogger(__name__)


def _pct(num: int, den: int) -> Optional[float]:
	"""Porcentaje redondeado; None ("n/a") si no hay denominador."""
	return round(100 * num / den, 1) if den else None


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
			payloads = [p.payload or {} for p in _scroll_all(client, c)]
			content = sum(1 for pl in payloads if is_content_node(pl))
			groupable_payloads = [pl for pl in payloads if is_groupable(pl)]
			groupable = len(groupable_payloads)
			hubs = sum(1 for pl in payloads if is_hub_node(pl))
			# Numerador ⊆ denominador: solo lo que la síntesis puede agrupar (mismo
			# predicado que group_by_session), así la cobertura nunca supera el 100%
			# ni la hunde un legacy sin sesión que jamás entrará en un hub.
			hubbed = sum(1 for pl in groupable_payloads if pl.get("hubbed"))
			out["collections"][c] = {
				"total": len(payloads),
				"content": content,
				"groupable": groupable,
				"hubs": hubs,
				"hubbed_members": hubbed,
				# Cobertura real: % de engrams agrupables que ya están en un hub.
				# El nombre dice la verdad (antes medía hubs/content = densidad, no
				# cobertura; con 1 hub por ~26 miembros daba 3.8% y parecía alarma).
				# Sin nada agrupable no hay nada que cubrir: None ("n/a"), no 0%.
				"hub_coverage_pct": _pct(hubbed, groupable),
				# Densidad de hubs (hubs por 100 engrams). Contexto, no salud.
				"hub_ratio_pct": _pct(hubs, content),
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
