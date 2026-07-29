#!/usr/bin/env python3
"""Colapsa los duplicados de archive_memories a un punto por mensaje lógico.

Causa (jul 2026): tras la migración XDG el chronicle perdió su registro y
re-ingería TODO el histórico cada noche; el id determinista incluye
`content[:100]` y el contenido deriva entre exportaciones (telemetría,
timestamps en tool outputs), así que cada pasada acuñaba ids nuevos para el
mismo mensaje. Resultado: 725K puntos para 232 sesiones, con slots repetidos
cientos de veces.

Qué hace:
- Conserva EXACTAMENTE un punto por (session_id, sequence_index, role) — gana
la copia con árbol de fragments, luego mayor created_at — y borra el resto.
- Poda los idea_fragments cuyo monolith padre cae en el colapso.
- Recablea el axón secuencial entre supervivientes tal y como lo deja la
ingesta (associations del nodo i → [{id: nodo i+1, weight 1.0}]).
- Las filas legacy sin metadatos de sesión no se tocan jamás.

Por defecto es un DRY-RUN que imprime el plan. `--execute` aplica (crea un
snapshot de la colección antes, salvo `--no-snapshot`).
"""

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dedup_archive")

COLLECTION = "archive_memories"
KEYED_TYPES = ("chronicle_node", "monolith_parent")


def choose_keepers(points: List[Dict[str, Any]], preferred_ids: frozenset = frozenset()) -> Tuple[Dict[Tuple, Dict[str, Any]], List[str]]:
	"""Separa supervivientes de bajas entre los nodos con clave lógica.

	points: [{"id": str, "payload": dict}]. Devuelve (keeper por clave, ids a
	borrar). Determinista: una copia referenciada por fragments gana (conserva
	el árbol monolith→fragments — los fragments solo existen en las copias de
	runs con el LLM encendido); después mayor created_at; a igualdad, menor id.
	"""
	groups: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
	for point in points:
		payload = point["payload"]
		key = (payload.get("session_id"), payload.get("sequence_index"), payload.get("role"))
		if key[0] is None or key[1] is None:
			continue
		groups[key].append(point)

	keepers: Dict[Tuple, Dict[str, Any]] = {}
	drop: List[str] = []
	for key, members in groups.items():
		members.sort(key=lambda p: (0 if str(p["id"]) in preferred_ids else 1, -float(p["payload"].get("created_at", 0) or 0), str(p["id"])))
		keepers[key] = members[0]
		drop.extend(str(p["id"]) for p in members[1:])
	return keepers, drop


def orphan_fragments(fragments: List[Dict[str, Any]], surviving_ids: set) -> List[str]:
	"""Fragments cuyo monolith padre no sobrevive: eran hijos de un duplicado."""
	return [str(f["id"]) for f in fragments if str(f["payload"].get("parent_id")) not in surviving_ids]


def forward_axons(keepers: Dict[Tuple, Dict[str, Any]]) -> List[Tuple[str, str]]:
	"""(id, next_id) por sesión en orden de sequence_index — el estado final que
	deja la ingesta original (el forward link machaca al backward)."""
	by_session: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
	for (session_id, idx, _role), point in keepers.items():
		by_session[str(session_id)].append((int(idx), str(point["id"])))
	links = []
	for chain in by_session.values():
		chain.sort()
		for (_, current), (_, following) in zip(chain, chain[1:]):
			links.append((current, following))
	return links


def _scan(client) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
	nodes, fragments = [], []
	offset = None
	while True:
		points, offset = client.scroll(COLLECTION, limit=1000, offset=offset, with_payload=True, with_vectors=False)
		for p in points:
			payload = p.payload or {}
			entry = {"id": str(p.id), "payload": payload}
			kind = payload.get("type")
			if kind in KEYED_TYPES:
				nodes.append(entry)
			elif kind == "idea_fragment":
				fragments.append(entry)
		if offset is None:
			return nodes, fragments


def main() -> None:
	parser = argparse.ArgumentParser(description="Colapsa duplicados de archive_memories")
	parser.add_argument("--execute", action="store_true", help="Aplicar de verdad (default: dry-run)")
	parser.add_argument("--no-snapshot", action="store_true", help="No crear snapshot previo (bajo tu responsabilidad)")
	args = parser.parse_args()

	from qdrant_client import QdrantClient

	import red_pill.config as cfg

	config = cfg.get_config() if hasattr(cfg, "get_config") else cfg
	# Snapshot y borrados masivos de una colección de cientos de miles de puntos
	# exceden el timeout por defecto del cliente (5s).
	client = QdrantClient(url=getattr(config, "QDRANT_URL", "http://localhost:6333"), api_key=getattr(config, "QDRANT_API_KEY", None), timeout=600)

	total = client.get_collection(COLLECTION).points_count
	logger.info(f"Escaneando {COLLECTION} ({total} puntos)...")
	nodes, fragments = _scan(client)

	fragment_parents = frozenset(str(f["payload"].get("parent_id")) for f in fragments)
	keepers, drop_nodes = choose_keepers(nodes, preferred_ids=fragment_parents)
	surviving = {str(point["id"]) for point in keepers.values()}
	drop_frags = orphan_fragments(fragments, surviving)
	links = forward_axons(keepers)

	logger.info(f"Nodos con clave: {len(nodes)} → supervivientes {len(keepers)}, bajas {len(drop_nodes)}")
	logger.info(f"Fragments: {len(fragments)} → huérfanos a podar {len(drop_frags)}")
	logger.info(f"Axones secuenciales a recablear: {len(links)}")
	logger.info(f"Intocables (legacy sin clave): {total - len(nodes) - len(fragments)}")

	if not args.execute:
		logger.info("[DRY RUN] Nada aplicado. Ejecuta con --execute para colapsar.")
		return

	if not args.no_snapshot:
		logger.info("Creando snapshot previo de la colección...")
		snapshot = client.create_snapshot(collection_name=COLLECTION)
		logger.info(f"Snapshot: {getattr(snapshot, 'name', snapshot)}")

	doomed = drop_nodes + drop_frags
	for start in range(0, len(doomed), 1000):
		client.delete(COLLECTION, points_selector=doomed[start : start + 1000], wait=True)
		logger.info(f"Borrados {min(start + 1000, len(doomed))}/{len(doomed)}")

	for current, following in links:
		try:
			client.set_payload(collection_name=COLLECTION, payload={"associations": [{"id": following, "weight": 1.0}]}, points=[current])
		except Exception as e:
			logger.debug(f"Recableado {current} → {following} falló: {e}")

	final = client.get_collection(COLLECTION).points_count
	logger.info(f"COLAPSO COMPLETO: {total} → {final} puntos ({total - final} retirados).")


if __name__ == "__main__":
	main()
