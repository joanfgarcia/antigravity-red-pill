#!/usr/bin/env python3
"""RFC-OLV-001 · F4 — auditoría re-ejecutable del olvido (solo lectura).

Responde, con números y sin escribir nada en el Búnker:

  1. ¿cuántas ramas hay, y cuántas tienen hojas vivas?
  2. ¿cuántos marcadores `hubbed` apuntan a un padre que no existe? (ceguera)
  3. ¿cuántas ramas sin hojas mienten en `hub_members_count`?
  4. ¿qué distribución de uso hay (`recall_count`)?
  5. ¿cuántas ramas se llevarían por delante el umbral bayesiano si siguiera vivo?

Uso:
    .venv/bin/python scripts/olvido_audit.py [--json]
"""

from __future__ import annotations

import collections
import json
import os
import sys
import time

from qdrant_client import QdrantClient
from qdrant_client import models as qm

HUB_FILTER = qm.Filter(
	should=[
		qm.FieldCondition(key="node_type", match=qm.MatchValue(value="synthesis_hub")),
		qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value="synthesis_hub")),
	]
)


def _client() -> QdrantClient:
	"""Cliente con la config real del proyecto.

	La clave vive en el `.env` que carga pydantic, no siempre en el entorno del
	proceso: leer solo `os.environ` devolvía 401 en el puesto del Operador y
	dejaba la sonda inservible.
	"""
	url = os.environ.get("QDRANT_URL")
	key = os.environ.get("QDRANT_API_KEY")
	if not url or not key:
		try:
			from red_pill.config import _cfg

			cfg = _cfg()
			url = url or cfg.QDRANT_URL
			key = key or cfg.QDRANT_API_KEY
		except Exception:
			pass
	return QdrantClient(url=url or "http://localhost:6333", api_key=key or None)


def _scroll_all(client: QdrantClient, collection: str, scroll_filter=None) -> list:
	out = []
	offset = None
	while True:
		batch, offset = client.scroll(
			collection_name=collection,
			scroll_filter=scroll_filter,
			limit=1000,
			offset=offset,
			with_payload=True,
			with_vectors=False,
		)
		out.extend(batch)
		if offset is None:
			return out


def audit_collection(client: QdrantClient, collection: str) -> dict:
	if not client.collection_exists(collection):
		return {"exists": False}
	points = _scroll_all(client, collection)
	hubs = [p for p in points if (p.payload or {}).get("lazarus_phase") == "synthesis_hub"]
	hub_ids = {str(p.id) for p in hubs}

	members = collections.Counter()
	hubbed = 0
	for p in points:
		pl = p.payload or {}
		if pl.get("hubbed") and pl.get("hub_id"):
			hubbed += 1
			members[str(pl["hub_id"])] += 1

	orphan_points = [p for p in points if (p.payload or {}).get("hubbed") and str((p.payload or {}).get("hub_id") or "") not in hub_ids]
	orphan_sessions = {str((p.payload or {}).get("session_id")) for p in orphan_points}
	leafless = [p for p in hubs if members.get(str(p.id), 0) == 0]
	lying = [p for p in leafless if int((p.payload or {}).get("hub_members_count") or 0) > 0]

	# Qué haría el umbral bayesiano heredado (se retira en F5): predicción, no acción.
	doomed = 0
	for p in hubs:
		pl = p.payload or {}
		if pl.get("immune") or members.get(str(p.id), 0) > 0:
			continue
		alpha = float(pl.get("utility_alpha", 1.0))
		beta = float(pl.get("utility_beta", 1.0))
		intensity = float(pl.get("intensity", 0.5))
		if alpha / (alpha + beta + 0.5) <= 0.2 or round(intensity * 0.85, 3) <= 0.05:
			doomed += 1

	dist = collections.Counter()
	for p in points:
		dist[min(int((p.payload or {}).get("recall_count") or 0), 5)] += 1

	return {
		"exists": True,
		"total": len(points),
		"hubs": len(hubs),
		"hubs_with_leaves": len(hubs) - len(leafless),
		"leafless": len(leafless),
		"leafless_with_lying_counter": len(lying),
		"hubbed_markers": hubbed,
		"orphan_markers": len(orphan_points),
		"orphan_sessions": len(orphan_sessions),
		"recall_count_dist": {str(k): v for k, v in sorted(dist.items())},
		"legacy_bayesian_would_delete_leafless": doomed,
		"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
	}


def main() -> int:
	client = _client()
	report = {c: audit_collection(client, c) for c in ("work_memories", "social_memories", "story_memories")}
	if "--json" in sys.argv:
		print(json.dumps(report, indent=1, ensure_ascii=False))
		return 0

	for name, data in report.items():
		if not data.get("exists"):
			print(f"{name}: (no existe)")
			continue
		print(f"\n{name}: {data['total']} puntos · {data['hubs']} ramas")
		print(
			f"  con hojas: {data['hubs_with_leaves']} · sin hojas: {data['leafless']} (mienten en el contador: {data['leafless_with_lying_counter']})"
		)
		print(f"  marcadores: {data['hubbed_markers']} · HUÉRFANOS: {data['orphan_markers']} en {data['orphan_sessions']} sesiones")
		print(f"  uso (0/1/2/3/4/5+): {data['recall_count_dist']}")
		if data["legacy_bayesian_would_delete_leafless"]:
			print(f"  el umbral heredado borraría {data['legacy_bayesian_would_delete_leafless']} ramas sin hojas")
	return 0


if __name__ == "__main__":
	sys.exit(main())
