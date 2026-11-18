"""Observabilidad del single-writer (D26).

Señales de salud para detectar regresiones silenciosas (el fallo "verde con 0
digerido"): cobertura de hubs, frescura del semáforo de situación y cobertura de
afinidad. Solo lectura; no modifica nada.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from red_pill.metabolism.hub_synthesis import HUB_MIN_SESSION_MEMBERS, is_content_node, is_groupable, is_hub_node

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
			points = _scroll_all(client, c)
			payloads = [p.payload or {} for p in points]
			content = sum(1 for pl in payloads if is_content_node(pl))
			groupable_payloads = [pl for pl in payloads if is_groupable(pl)]
			groupable = len(groupable_payloads)
			hubs = sum(1 for pl in payloads if is_hub_node(pl))
			# MEM-011 D-SH-02: las partes comparten `node_type=synthesis_hub`; el
			# papel vive en `hub_role`. Los instrumentos se leen POR ROL: contar el
			# árbol entero como "hubs" infla la densidad ~1:3 por diseño (D-SH-06).
			hubs_part = sum(1 for pl in payloads if is_hub_node(pl) and str(pl.get("hub_role") or "") == "part")
			hubs_root = hubs - hubs_part
			# Numerador ⊆ denominador: solo lo que la síntesis puede agrupar (mismo
			# predicado que group_by_session), así la cobertura nunca supera el 100%
			# ni la hunde un legacy sin sesión que jamás entrará en un hub.
			hubbed = sum(1 for pl in groupable_payloads if pl.get("hubbed"))
			# RFC-OLV-001 §1: el flag `hubbed` no prueba que el padre exista. Un
			# marcador cuyo `hub_id` no resuelve (1.962 en el Búnker el 2026-11-16)
			# inflaba esta métrica y, peor, era invisible al recall por el filtro
			# estructural. La cobertura cuenta NODOS que existen.
			hub_ids = {str(p.id) for p in points if is_hub_node(p.payload or {})}
			orphans = sum(1 for pl in groupable_payloads if pl.get("hubbed") and str(pl.get("hub_id") or "") not in hub_ids)
			# Un marcador huérfano en una sesión de UN solo miembro no es una fuga:
			# la síntesis exige `len(members) >= 2` (hub_synthesis `_synthesize_one`),
			# así que esa sesión jamás tendrá hub y el marcador es residuo de una
			# poda/olvido anterior. Contarlo dejaba la lámpara en rojo para siempre
			# (40 marcadores, 40 sesiones de 1 miembro, medido el 2026-11-18) y
			# enmascaraba las fugas de verdad. Verdad en dos capas: crudo y accionable.
			sessions_size: Dict[str, int] = {}
			for pl in groupable_payloads:
				key = str(pl.get("session_id") or "")
				sessions_size[key] = sessions_size.get(key, 0) + 1
			orphans_stale = sum(
				1
				for pl in groupable_payloads
				if pl.get("hubbed")
				and str(pl.get("hub_id") or "") not in hub_ids
				and sessions_size.get(str(pl.get("session_id") or ""), 0) < HUB_MIN_SESSION_MEMBERS
			)
			covered = hubbed - orphans
			out["collections"][c] = {
				"total": len(payloads),
				"content": content,
				"groupable": groupable,
				"hubs": hubs,
				# Rol del árbol (MEM-011): raíces frente a partes. `hubs` es el total
				# de nodos; la densidad se mide sobre raíces para que encender el
				# empaquetado por polaroids no parezca que triplica los hubs.
				"hubs_root": hubs_root,
				"hubs_part": hubs_part,
				"hubbed_members": hubbed,
				"orphan_markers": orphans,
				"orphan_markers_stale": orphans_stale,
				"hub_integrity_ok": orphans_stale == orphans,
				# Cobertura real: % de engrams agrupables que ya están en un hub.
				# El nombre dice la verdad (antes medía hubs/content = densidad, no
				# cobertura; con 1 hub por ~26 miembros daba 3.8% y parecía alarma).
				# Sin nada agrupable no hay nada que cubrir: None ("n/a"), no 0%.
				"hub_coverage_pct": _pct(covered, groupable),
				# Densidad de hubs (raíces por 100 engrams). Contexto, no salud. Las
				# partes no cuentan: son el techo del árbol, no otra unidad de sesión.
				"hub_ratio_pct": _pct(hubs_root, content),
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
