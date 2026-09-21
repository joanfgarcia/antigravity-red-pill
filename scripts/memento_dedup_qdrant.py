#!/usr/bin/env python3
"""memento_dedup_qdrant.py — colapsa duplicados sembrados en work/social (MEM-006 P1-B).

El refine multi-idea generó varios `refine/*.md` con el MISMO cuerpo y títulos
distintos; el ascenso los subió todos → el recall devuelve la misma idea repetida.
Este script agrupa por (`session_id`, `source_lines`, hash del cuerpo), deja UN
superviviente por grupo (score compuesto) y borra las réplicas **in-place** (sin
re-resiembra). NO toca los `refine/*.md` de disco.

Dry-run por defecto; `--apply` ejecuta por lotes.

Uso:
	uv run python scripts/memento_dedup_qdrant.py
	uv run python scripts/memento_dedup_qdrant.py --apply
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memento_dedup_qdrant")

COLLECTIONS = ("work_memories", "social_memories")


def _score(payload: Dict[str, Any]) -> Tuple[float, float, int, str]:
	"""Score compuesto determinista para elegir el superviviente."""
	body = str(payload.get("content") or "")
	return (
		float(payload.get("significance", 0.0) or 0.0),
		float(payload.get("category_score", 0.0) or 0.0),
		len(body),
		hashlib.sha256(body.encode("utf-8")).hexdigest(),
	)


def plan_dedup(points: List[Tuple[Any, Dict[str, Any]]]) -> Dict[str, Any]:
	"""Calcula el plan de borrado (puro, testeable).

	Devuelve {"to_delete": [id...], "groups": N, "duplicates": M}.
	"""
	groups: Dict[Tuple[str, str, str], List[Tuple[Any, Dict[str, Any]]]] = {}
	for pid, payload in points:
		payload = payload or {}
		if payload.get("origin") != "memento":
			continue
		body = str(payload.get("content") or "")
		key = (
			str(payload.get("session_id") or ""),
			str(payload.get("source_lines") or ""),
			hashlib.sha256(body.encode("utf-8")).hexdigest(),
		)
		groups.setdefault(key, []).append((pid, payload))

	to_delete: List[str] = []
	dup_groups = 0
	for entries in groups.values():
		if len(entries) < 2:
			continue
		dup_groups += 1
		winner = max(entries, key=lambda e: _score(e[1]))
		for pid, _pl in entries:
			if str(pid) != str(winner[0]):
				to_delete.append(str(pid))
	return {"to_delete": to_delete, "groups": len(groups), "duplicates": dup_groups}


def main() -> int:
	parser = argparse.ArgumentParser(description="Colapsa duplicados de engramas curados (P1-B).")
	parser.add_argument("--apply", action="store_true", help="Ejecuta (por defecto solo dry-run).")
	parser.add_argument("--batch", type=int, default=500)
	args = parser.parse_args()

	sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
	from qdrant_client.http import models as _m

	from red_pill.memory import MemoryManager

	mem = MemoryManager()
	total = 0
	for coll in COLLECTIONS:
		if not mem.client.collection_exists(coll):
			continue
		points: List[Tuple[Any, Dict[str, Any]]] = []
		offset = None
		while True:
			batch, offset = mem.client.scroll(coll, limit=1000, offset=offset, with_payload=True, with_vectors=False)
			points.extend((p.id, p.payload) for p in batch)
			if offset is None:
				break
		plan = plan_dedup(points)
		logger.info(f"{coll}: {plan['groups']} grupos, {plan['duplicates']} con duplicados, {len(plan['to_delete'])} réplicas a borrar.")
		total += len(plan["to_delete"])
		if args.apply and plan["to_delete"]:
			for i in range(0, len(plan["to_delete"]), args.batch):
				chunk = plan["to_delete"][i : i + args.batch]
				mem.client.delete(coll, points_selector=_m.PointIdsList(points=chunk), wait=True)
			logger.info(f"{coll}: borradas {len(plan['to_delete'])}.")
	logger.info(f"TOTAL réplicas: {total}. {'APLICADO' if args.apply else 'DRY-RUN (usa --apply)'}.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
