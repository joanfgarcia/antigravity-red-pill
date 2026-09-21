#!/usr/bin/env python3
"""memento_backfill_dates.py — backfill de fechas de la resiembra (G9, single-writer).

La primera resiembra ascendió ~9.341 engramas con `created_at` = momento de la
ascensión (2026-09-17), no la fecha real de la sesión → el eje temporal del hilo
de Ariadna quedó colapsado. Este script lo repara:

- `created_at` ← fecha REAL de la sesión (del `memento_registry.json`).
- `ascended_at` ← el `created_at` actual (momento de la ascensión, preservado).
- `node_type`   ← "memento_engram".

Idempotente: los puntos que ya tienen `ascended_at` se saltan (no reaplica).
Dry-run por defecto; `--apply` ejecuta en lotes.

Uso:
	uv run python scripts/memento_backfill_dates.py
	uv run python scripts/memento_backfill_dates.py --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memento_backfill_dates")

COLLECTIONS = ("work_memories", "social_memories")


def _iso_to_epoch(iso: Any) -> Optional[float]:
	if not iso:
		return None
	try:
		return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
	except Exception:
		return None


def plan_backfill(points: List[Tuple[Any, Dict[str, Any]]], registry_state: Dict[str, Any]) -> List[Dict[str, Any]]:
	"""Calcula las actualizaciones de payload (puro, testeable).

	`points` = [(id, payload)]. `registry_state` = {"registry": {source: {sid: entry}}}.
	Devuelve [{"id":..., "payload": {...}}], saltando ya-backfilled y sesiones sin
	fecha conocida.
	"""
	reg = (registry_state or {}).get("registry", {}) or {}
	out: List[Dict[str, Any]] = []
	for pid, payload in points:
		payload = payload or {}
		if payload.get("origin") != "memento":
			continue
		if payload.get("ascended_at"):
			continue  # ya backfilled (idempotente)
		source = str(payload.get("source") or "")
		sid = str(payload.get("session_id") or "")
		epoch = _iso_to_epoch((reg.get(source, {}) or {}).get(sid, {}).get("created_at"))
		if epoch is None:
			continue  # sin fecha de sesión conocida: no se toca
		upd: Dict[str, Any] = {"created_at": epoch, "node_type": "memento_engram"}
		current = payload.get("created_at")
		if isinstance(current, (int, float)):
			upd["ascended_at"] = float(current)
		out.append({"id": str(pid), "payload": upd})
	return out


def main() -> int:
	parser = argparse.ArgumentParser(description="Backfill de fechas de engramas ascendidos (G9).")
	parser.add_argument("--apply", action="store_true", help="Ejecuta (por defecto solo dry-run).")
	parser.add_argument("--batch", type=int, default=500)
	args = parser.parse_args()

	sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
	from red_pill.memento.registry import MementoRegistry
	from red_pill.memory import MemoryManager

	registry = MementoRegistry()
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
		plan = plan_backfill(points, registry.state)
		logger.info(f"{coll}: {len(plan)} de {len(points)} puntos a backfillear.")
		total += len(plan)
		if args.apply and plan:
			from qdrant_client.http import models as _m

			for i in range(0, len(plan), args.batch):
				chunk = plan[i : i + args.batch]
				ops = [
					_m.SetPayloadOperation(set_payload=_m.SetPayload(payload=it["payload"], points=[it["id"]]))
					for it in chunk
				]
				mem.client.batch_update_points(collection_name=coll, update_operations=ops)
			logger.info(f"{coll}: aplicados {len(plan)}.")
	logger.info(f"TOTAL a backfillear: {total}. {'APLICADO' if args.apply else 'DRY-RUN (usa --apply)'}.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
