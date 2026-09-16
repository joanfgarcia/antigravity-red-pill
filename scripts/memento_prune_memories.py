#!/usr/bin/env python3
"""memento_prune_memories.py — purga de engramas curados por umbral (2026-09-15).

La siembra guarda en cada engrama `origin=memento` + `significance` (y
`category_score`, `engine`, `prompt_version`...). Si tras afinar el umbral
(p.ej. bajar MEMENTO_GATE_MIN_SIGNIFICANCE) queremos descartar lo que ya se
subió con un umbral demasiado bajo, este script purga de work/social_memories los
engramas curados con `significance` por debajo de un umbral.

Dry-run por defecto; `--apply` ejecuta. Recomendado hacer backup (snapshot) antes.

Uso:
	uv run python scripts/memento_prune_memories.py --min-significance 0.4
	uv run python scripts/memento_prune_memories.py --min-significance 0.4 --apply
	uv run python scripts/memento_prune_memories.py --min-significance 0.4 --max-category-score 0.5 --apply
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List


def _collect(col: str, mm: Any, min_sig: float, max_cat: float | None) -> List[Dict[str, Any]]:
	"""Engramas curados (origin=memento) con significance < min_sig (y category_score
	<= max_cat si se da)."""

	offset = None
	hits = []
	while True:
		batch, offset = mm.client.scroll(collection_name=col, limit=256, with_payload=True, with_vectors=False, offset=offset)
		for p in batch:
			pl = p.payload or {}
			if pl.get("origin") != "memento":
				continue
			sig = float(pl.get("significance", 1.0) or 1.0)
			if sig >= min_sig:
				continue
			if max_cat is not None:
				cat = float(pl.get("category_score", 0.5) or 0.5)
				if cat > max_cat:
					continue
			hits.append(
				{"id": str(p.id), "significance": sig, "category_score": pl.get("category_score"), "content": str(pl.get("content") or "")[:60]}
			)
		if offset is None:
			break
	return hits


def main() -> None:
	parser = argparse.ArgumentParser(description="Purga de engramas curados por umbral de significance.")
	parser.add_argument("--min-significance", type=float, required=True, help="Umbral: se purgan los engramas con significance < este valor")
	parser.add_argument("--max-category-score", type=float, default=None, help="Opcional: solo purgar los de esta categoría (≤ umbral → social)")
	parser.add_argument("--collection", choices=["work_memories", "social_memories", "both"], default="both")
	parser.add_argument("--apply", action="store_true", help="Ejecuta la purga (por defecto: dry-run)")
	args = parser.parse_args()

	from red_pill.memory import MemoryManager

	mm = MemoryManager()
	cols = ["work_memories", "social_memories"] if args.collection == "both" else [args.collection]
	total = 0
	for col in cols:
		if not mm.client.collection_exists(col):
			continue
		hits = _collect(col, mm, args.min_significance, args.max_category_score)
		total += len(hits)
		print(
			f"[PRUNE] {col}: {len(hits)} engramas con significance < {args.min_significance}"
			+ (f" y category_score <= {args.max_category_score}" if args.max_category_score is not None else "")
		)
		for h in hits[:8]:
			print(f"   sig={h['significance']} cat={h['category_score']} | {h['content']}")
		if hits and args.apply:
			from qdrant_client.http import models

			mm.client.delete(collection_name=col, points_selector=models.PointIdsList(points=[h["id"] for h in hits]))
			print(f"[PRUNE] {col}: {len(hits)} purgados")
	if not args.apply:
		print(f"[PRUNE] DRY-RUN: {total} engramas a purgar en total (usa --apply). Haz snapshot antes.")
	else:
		print(f"[PRUNE] {total} engramas purgados.")


if __name__ == "__main__":
	main()
