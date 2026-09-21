#!/usr/bin/env python3
"""interactive_refine.py — proceso APARTE para los engramas interactivos (D13).

Los engramas que el agente decide guardar "en caliente" son especiales
(`node_type="interactive_engram"`): no se agrupan por sesión ni entran en la
ingesta normal. Este proceso, separado de las fases del sueño, los recorre,
los **refina** (limpieza/normalización; inyectable) y los **marca**
(`interactive_refined=True`) para no reprocesarlos.

Dry-run por defecto; `--apply` ejecuta.

Uso:
	uv run python scripts/interactive_refine.py
	uv run python scripts/interactive_refine.py --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("interactive_refine")

COLLECTIONS = ("work_memories", "social_memories")
NODE_TYPE = "interactive_engram"


def plan_interactive(points: List[Tuple[Any, Dict[str, Any]]]) -> List[str]:
	"""ids de engramas interactivos aún sin refinar (puro, testeable)."""
	out: List[str] = []
	for pid, payload in points:
		payload = payload or {}
		if payload.get("node_type") != NODE_TYPE:
			continue
		if payload.get("interactive_refined"):
			continue
		out.append(str(pid))
	return out


def _default_refiner(text: str) -> str:
	"""Refinado por defecto: no reescribe (el agente ya curó). Placeholder para LLM."""
	return text


def main() -> int:
	parser = argparse.ArgumentParser(description="Refina/marca engramas interactivos (D13).")
	parser.add_argument("--apply", action="store_true", help="Ejecuta (por defecto solo dry-run).")
	args = parser.parse_args()

	sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
	import red_pill.config as cfg
	from red_pill.memory import MemoryManager

	if not bool(getattr(cfg, "SW_INTERACTIVE_PHASE_ENABLED", False)):
		logger.info("SW_INTERACTIVE_PHASE_ENABLED off; nada que hacer.")
		return 0

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
		ids = plan_interactive(points)
		logger.info(f"{coll}: {len(ids)} interactivos a procesar.")
		total += len(ids)
		if args.apply and ids:
			mem.client.set_payload(coll, payload={"interactive_refined": True}, points=ids)
	logger.info(f"TOTAL interactivos: {total}. {'APLICADO' if args.apply else 'DRY-RUN (usa --apply)'}.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
