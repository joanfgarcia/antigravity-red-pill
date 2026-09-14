#!/usr/bin/env python3
"""memento_refine_rescore.py — re-refinado con category_score (Fase 4, 2026-09-14).

El curador LLM clasifica work/social correctamente EN EL REFINE (ratio category_score
0-1; verificado: técnico → 0.8). El clasificador standalone (`_classify_llm`) es
débil con el LLM local (tiny_aya devuelve 0.0 siempre). Por eso la clasificación
debe vivir en el refine.

Este script re-ejecuta SOLO el refine (no el distill — mucho más barato) sobre los
distill existentes para regenerar los refine con `category_score`. Sin LLM no se
hace nada (el refine necesita el curador).

Uso:
    uv run python scripts/memento_refine_rescore.py --limit 50   # las primeras N sesiones
    uv run python scripts/memento_refine_rescore.py --all         # todo el árbol
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List


def _sections_from_distill(distill_dir: Path) -> List[Dict[str, Any]]:
	"""Construye las secciones desde los distill EXISTENTES (sin re-destilar)."""
	from red_pill.memento.ascension import parse_refine

	sections = []
	for p in sorted(distill_dir.glob("*.md")):
		fm, body = parse_refine(p.read_text(encoding="utf-8"))
		if not body:
			continue
		nnn = str(fm.get("section") or p.name[:3])
		sections.append(
			{
				"nnn": nnn,
				"file": p.name,
				"title": str(fm.get("title") or p.stem),
				"summary": body,
				"source_lines": str(fm.get("source_lines") or ""),
				"fragment": fm.get("fragment"),
				"fragments_total": fm.get("fragments_total"),
			}
		)
	return sections


def main() -> None:
	parser = argparse.ArgumentParser(description="Re-refinado con category_score (LLM).")
	parser.add_argument("--limit", type=int, default=None, help="Solo las primeras N sesiones")
	parser.add_argument("--all", action="store_true", help="Todo el árbol (default: solo sesiones sin refine)")
	args = parser.parse_args()

	from red_pill.memento import get_memento_root
	from red_pill.memento.agentic import http_transport
	from red_pill.memento.registry import MementoRegistry

	root = get_memento_root()
	registry = MementoRegistry()
	stats = {"sesiones": 0, "refine_escritos": 0, "errores": 0}

	dirs = sorted(
		(src, sid, (Path(root) / e["dir"]))
		for src, sessions in registry.state["registry"].items()
		for sid, e in (sessions.items() if isinstance(sessions, dict) else [])
		if e.get("dir")
	)

	processed = 0
	for source, session_id, session_dir in dirs:
		distill_dir = session_dir / "distill"
		refine_dir = session_dir / "refine"
		if not distill_dir.is_dir() or not any(distill_dir.glob("*.md")):
			continue
		has_refine = refine_dir.is_dir() and any(refine_dir.glob("*.md"))
		if has_refine and not args.all:
			continue
		if args.limit is not None and processed >= args.limit:
			break

		sections = _sections_from_distill(distill_dir)
		if not sections:
			continue
		try:
			from red_pill.memento.agentic import refine_session

			refine_session(root, session_dir.relative_to(root).as_posix(), session_id, source, sections, [], http_transport, 0.3)
			stats["sesiones"] += 1
			stats["refine_escritos"] += len(list(refine_dir.glob("*.md"))) if refine_dir.is_dir() else 0
			processed += 1
		except Exception as e:
			stats["errores"] += 1
			print(f"[RESCORE] error en {session_dir}: {e}")

	print(f"[RESCORE] sesiones re-refinadas: {stats['sesiones']} | refine escritos: {stats['refine_escritos']} | errores: {stats['errores']}")


if __name__ == "__main__":
	main()
