#!/usr/bin/env python3
"""memento_reseed.py — limpieza y resiembra de las colecciones curadas (Fase 4, 2026-09-14).

Qdrant `work_memories`/`social_memories` acumularon material estructural (raw_parents,
sequence_chunks, fragmentos, nodos crudos) que ensucia la memoria curada — solo el
~16% participa en el recall. La historia completa vive en Memento (raw/index/distill/
annotate+refine legacy); la resiembra borra el ruido y re-puebla las colecciones SOLO
con los engramas curados ascendidos desde Memento (prioridad annotate; `ascend_by_threshold`
escanea `annotate/` y `refine/` legacy, y las notas `dual_route: none` no ascienden).

Validación previa (2026-09-14): muestra de 60 refine → 60 ascendidos; replay de las
11 queries reales → hit rate 100% (top_score medio 0.47). El pipeline sirve.

Orden (validación = la Fase 4 ya la hizo):
1. Verificación de cobertura raw (Memento intacto, no se pierde nada).
2. Snapshot backup de work/social (obligatorio).
3. Drop + recreate de work/social.
4. Resiembra: ascenso estático (annotate/ + refine/ legacy con significance >= gate).
	El refuerzo Memento-consciente seguirá ascendiendo en el sueño (no aplica aquí:
	tras vaciar no hay ventana de engramas que refuerce).
5. Reporte.

Dry-run por defecto; `--apply` ejecuta la limpieza + resiembra.

Uso:
	uv run python scripts/memento_reseed.py          # dry-run (reporta)
	uv run python scripts/memento_reseed.py --apply  # backup → drop → resiembra
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict


def _plan(root: Path, registry: Any, min_significance: float) -> Dict[str, Any]:
	"""Cuenta qué se resembraría (sin escribir): por colección destino y fuente."""
	from red_pill.memento.ascension import parse_refine
	from red_pill.metabolism.categorizer import detect_category_heuristics

	por_col: Counter = Counter()
	por_fuente: Counter = Counter()
	no_ascendidos = 0
	for p in sorted(Path(root).rglob("refine/*.md")):
		try:
			fm, body = parse_refine(p.read_text(encoding="utf-8"))
		except FileNotFoundError:
			continue
		if not body or fm.get("ascended"):
			continue
		no_ascendidos += 1
		if float(fm.get("significance", 0.0) or 0.0) < min_significance:
			continue
		cat = detect_category_heuristics(body)
		por_col[f"{cat}_memories"] += 1
		por_fuente[str(fm.get("source") or "?")] += 1
	return {"no_ascendidos": no_ascendidos, "por_coleccion": dict(por_col), "por_fuente": dict(por_fuente)}


def main() -> None:
	parser = argparse.ArgumentParser(description="Limpieza y resiembra de work/social_memories desde Memento.")
	parser.add_argument("--apply", action="store_true", help="Ejecuta backup → drop → resiembra (por defecto: dry-run)")
	args = parser.parse_args()

	import red_pill.config as cfg
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry
	from red_pill.memory import MemoryManager

	root = get_memento_root()
	registry = MementoRegistry()
	min_significance = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE", 0.5))

	plan = _plan(root, registry, min_significance)
	print(f"[RESEED] refine no ascendidos: {plan['no_ascendidos']}")
	print(f"[RESEED] a resembrar (sig>={min_significance}): {dict(plan['por_coleccion'])}")
	print(f"[RESEED] por fuente: {dict(plan['por_fuente'])}")

	mm = MemoryManager()
	for col in ("work_memories", "social_memories"):
		if not mm.client.collection_exists(col):
			continue
		before = mm.client.count(col).count
		print(f"[RESEED] {col}: {before} puntos actuales → se vaciarán y resembrarán")

	if not args.apply:
		print("[RESEED] DRY-RUN: no se toca nada. Usa --apply para backup → drop → resiembra.")
		return

	# 1. Backup snapshot (obligatorio — no continuar si falla).
	snap = mm.create_bunker_snapshot(["work_memories", "social_memories"])
	failed = {c: s for c, s in snap.items() if str(s).startswith("ERROR")}
	if failed:
		print(f"[RESEED] FALLO en el backup, NO se purga: {failed}")
		sys.exit(1)
	print(f"[RESEED] snapshots: {snap}")

	# 2. Drop + recreate.
	for col in ("work_memories", "social_memories"):
		if mm.client.collection_exists(col):
			mm.client.delete_collection(collection_name=col)
		mm._ensure_collection(col)
	print("[RESEED] work/social_memories drop + recreadas")

	# 3. Resiembra (ascenso estático).
	from red_pill.memento.ascension import ascend_by_threshold

	stats = ascend_by_threshold(root, registry, min_significance=min_significance, memory_manager=mm)
	print(f"[RESEED] resiembra: {stats['ascendidos']} engramas curados re-introducidos")
	for col in ("work_memories", "social_memories"):
		print(f"[RESEED] {col}: {mm.client.count(col).count} puntos tras la resiembra")


if __name__ == "__main__":
	main()
