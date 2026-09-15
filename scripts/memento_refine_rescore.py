#!/usr/bin/env python3
"""memento_refine_rescore.py — re-refinado con category_score (Fase 4, 2026-09-14).

El curador LLM clasifica work/social correctamente EN EL REFINE (ratio category_score
0-1; verificado: técnico → 0.8). El clasificador standalone (`_classify_llm`) es
débil con el LLM local (tiny_aya devuelve 0.0 siempre). Por eso la clasificación
debe vivir en el refine.

Este script re-ejecuta SOLO el refine (no el distill — mucho más barato) sobre los
distill existentes para regenerar los refine con `category_score`. Sin LLM no se
hace nada (el refine necesita el curador). Debe correr con el modelo que clasifica
bien (tiny_aya_water), NO con granite (decisión 2026-09-15).

Reanudable por sesión (2026-09-15): `--list-pending` imprime el array JSON de las
sesiones cuyo refine aún no tiene category_score; `--process-one <dir_rel>` re-refina
UNA sesión (idempotente). Es la función por elemento del job element_job
`configs/jobs/memento_rescore.yaml` (RP_ELEMENT = dir_rel).

Uso:
	uv run python scripts/memento_refine_rescore.py --list-pending
	uv run python scripts/memento_refine_rescore.py --process-one 2026-09/opencode/x
	uv run python scripts/memento_refine_rescore.py --all          # batch (todo)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List


def _session_dirs(registry: Any, root: Path) -> List:
	"""[(source, session_id, dir_rel, session_dir)] con distill/ existente."""
	out = []
	for src, sessions in registry.state["registry"].items():
		if not isinstance(sessions, dict):
			continue
		for sid, e in sessions.items():
			dir_rel = e.get("dir")
			if not dir_rel:
				continue
			session_dir = Path(root) / dir_rel
			if (session_dir / "distill").is_dir() and any((session_dir / "distill").glob("*.md")):
				out.append((src, sid, dir_rel, session_dir))
	return out


def _has_category_score(session_dir: Path) -> bool:
	"""True si algún refine de la sesión ya lleva category_score en el frontmatter."""
	from red_pill.memento.ascension import parse_refine

	refine_dir = session_dir / "refine"
	if not refine_dir.is_dir():
		return False
	for p in refine_dir.glob("*.md"):
		try:
			fm, _ = parse_refine(p.read_text(encoding="utf-8"))
		except Exception:
			continue
		if fm.get("category_score") is not None:
			return True
	return False


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


def list_pending(registry: Any, root: Path) -> List[str]:
	"""Sesiones (dir_rel) cuyo refine aún no tiene category_score."""
	pending = []
	for _src, _sid, dir_rel, session_dir in _session_dirs(registry, root):
		if not _has_category_score(session_dir):
			pending.append(dir_rel)
	return sorted(pending)


def process_one(root: Path, registry: Any, dir_rel: str) -> Dict[str, Any]:
	"""Re-refina UNA sesión (idempotente: salta si ya tiene category_score)."""
	from red_pill.memento.agentic import http_transport, refine_session

	session_dir = Path(root) / dir_rel
	if _has_category_score(session_dir):
		return {"skipped": True, "dir": dir_rel, "reason": "ya tiene category_score"}

	# localiza (source, session_id) para el dir_rel
	source = session_id = ""
	for src, sessions in registry.state["registry"].items():
		if not isinstance(sessions, dict):
			continue
		for sid, e in sessions.items():
			if e.get("dir") == dir_rel:
				source, session_id = src, sid
				break
		if source:
			break

	sections = _sections_from_distill(session_dir / "distill")
	if not sections:
		return {"skipped": True, "dir": dir_rel, "reason": "sin distill"}

	refine_session(root, dir_rel, session_id or dir_rel, source or "?", sections, [], http_transport, 0.3)
	return {"dir": dir_rel, "refine_escritos": len(list((session_dir / "refine").glob("*.md"))) if (session_dir / "refine").is_dir() else 0}


def main() -> None:
	parser = argparse.ArgumentParser(description="Re-refinado con category_score (LLM, Aya).")
	parser.add_argument("--list-pending", action="store_true", help="Imprime el JSON de sesiones sin category_score")
	parser.add_argument("--process-one", action="store_true", help="Re-refina UNA sesión (dir_rel desde RP_ELEMENT)")
	parser.add_argument("--limit", type=int, default=None, help="Batch: solo las primeras N sesiones")
	parser.add_argument("--all", action="store_true", help="Batch: todo el árbol")
	args = parser.parse_args()

	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry

	root = get_memento_root()
	registry = MementoRegistry()

	if args.list_pending:
		print(json.dumps(list_pending(registry, root)))
		return

	if args.process_one or os.environ.get("RP_ELEMENT"):
		dir_rel = json.loads(os.environ["RP_ELEMENT"]) if os.environ.get("RP_ELEMENT") else args.process_one
		result = process_one(root, registry, dir_rel)
		print(f"[RESCORE] {result}")
		return

	# Batch (compatibilidad con el modo antiguo)
	stats = {"sesiones": 0, "refine_escritos": 0, "errores": 0}
	processed = 0
	for _src, _sid, dir_rel, session_dir in _session_dirs(registry, root):
		if args.limit is not None and processed >= args.limit:
			break
		if _has_category_score(session_dir) and not args.all:
			continue
		try:
			r = process_one(root, registry, dir_rel)
			if not r.get("skipped"):
				stats["sesiones"] += 1
				stats["refine_escritos"] += r.get("refine_escritos", 0)
				processed += 1
		except Exception as e:
			stats["errores"] += 1
			print(f"[RESCORE] error en {dir_rel}: {e}")
	print(f"[RESCORE] sesiones re-refinadas: {stats['sesiones']} | refine escritos: {stats['refine_escritos']} | errores: {stats['errores']}")


if __name__ == "__main__":
	main()
