#!/usr/bin/env python3
"""memento_refine_rescore.py — re-scoring de notas annotate + reparación legacy de refine.

QUÉ ES / PARA QUÉ (2026-09-24, notes-first)
	La etapa annotate deja en el árbol las notas que el routing dual no resolvió
	(`dual_route: none` — zona muerta o bajo gate): "queda para re-scoring futuro".
	Este script es ese re-scoring, y trabaja **sobre las NOTAS primero**:

	- `--target notes` (default): re-puntúa con el MISMO contrato de annotate
		(`task=annotate`, `granite_8b`) las notas sin ruta y **sin ascender**,
		y actualiza `work_score`/`social_score`/`dual_route` en el frontmatter.
		Las que resuelven quedan ascendibles por el flujo normal.
	- `--target refines` (LEGACY, solo reparación): re-refina sesiones **sin
		notas** cuyo `refine/` no tiene `category_score` (re-inferir el ratio sobre
		distills existentes). Corre con el modelo del clasificador legacy
		(`tiny_aya_water`, decisión 2026-09-15). **Nunca toca sesiones con notas**:
		si hay notas, manda la nota (annotate-first).

	Modelo: en las notas se fuerza `annotate`+`granite_8b` (coherencia con el
	scorer que produjo el resto del corpus); tiny queda para el carril refine
	legacy, donde la decisión 15-sep documenta mejor clasificación — con la
	salvedad de que el clasificador standalone con tiny devuelve 0.0 siempre.

	Reanudable por sesión: `--list-pending` imprime el array JSON de sesiones
	candidatas; `--process-one` procesa UNA (dir_rel vía RP_ELEMENT). Es la
	función por elemento del job element_job `configs/jobs/memento_rescore.yaml`.

Uso:
	uv run python scripts/memento_refine_rescore.py --list-pending [--target notes|refines]
	uv run python scripts/memento_refine_rescore.py --process-one [--target ...]
	uv run python scripts/memento_refine_rescore.py --all [--target ...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

NOTES_MODEL = "granite_8b"


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


def _has_annotate_notes(session_dir: Path) -> bool:
	return (session_dir / "annotate").is_dir() and any((session_dir / "annotate").glob("*.md"))


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


def _notes_pending(session_dir: Path) -> List[Path]:
	"""Notas annotate sin ruta resuelta (dual_route none/ausente) y sin ascender."""
	from red_pill.memento.ascension import parse_refine

	out: List[Path] = []
	annotate_dir = session_dir / "annotate"
	if not annotate_dir.is_dir():
		return out
	for p in sorted(annotate_dir.glob("*.md")):
		try:
			fm, body = parse_refine(p.read_text(encoding="utf-8"))
		except Exception:
			continue
		if not body or fm.get("ascended"):
			continue
		if str(fm.get("dual_route") or "none").strip().lower() in ("none", "unstable", ""):
			out.append(p)
	return out


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


@contextmanager
def _notes_contract():
	"""Fuerza el contrato de annotate (task + modelo) durante el re-scoring de notas."""
	prev_task = os.environ.get("RP_LLM_TASK")
	prev_model = os.environ.get("RP_LLM_MODEL")
	os.environ["RP_LLM_TASK"] = "annotate"
	os.environ["RP_LLM_MODEL"] = NOTES_MODEL
	try:
		yield
	finally:
		for key, prev in (("RP_LLM_TASK", prev_task), ("RP_LLM_MODEL", prev_model)):
			if prev is None:
				os.environ.pop(key, None)
			else:
				os.environ[key] = prev


def _update_note_scores(path: Path, work: float, social: float, route: str) -> None:
	"""Actualiza work_score/social_score/dual_route del frontmatter (atómico)."""
	values = {"work_score": f"{work:.2f}", "social_score": f"{social:.2f}", "dual_route": route}
	text = path.read_text(encoding="utf-8")

	def repl(match: "re.Match") -> str:
		return f"{match.group(1)}: {values[match.group(1)]}"

	new_text = re.sub(r"^(work_score|social_score|dual_route):.*$", repl, text, count=3, flags=re.MULTILINE)
	if new_text != text:
		tmp = path.with_suffix(path.suffix + ".tmp")
		tmp.write_text(new_text, encoding="utf-8")
		tmp.replace(path)


def list_pending(registry: Any, root: Path, target: str = "notes", limit: Optional[int] = None) -> List[str]:
	"""Sesiones candidatas según `target` (notes-first); `limit` acota (pilotos)."""
	pending = []
	for _src, _sid, dir_rel, session_dir in _session_dirs(registry, root):
		if target == "notes":
			if _notes_pending(session_dir):
				pending.append(dir_rel)
		else:  # refines (legacy): solo sesiones SIN notas
			if not _has_annotate_notes(session_dir) and not _has_category_score(session_dir):
				pending.append(dir_rel)
	pending = sorted(pending)
	return pending[:limit] if limit else pending


def process_one(root: Path, registry: Any, dir_rel: str, target: str = "notes", transport: Optional[Any] = None) -> Dict[str, Any]:
	"""Procesa UNA sesión según `target`. Idempotente."""
	from red_pill.memento.agentic import http_transport

	if transport is None:
		transport = http_transport

	session_dir = Path(root) / dir_rel

	if target == "notes":
		from red_pill.memento.agentic import annotate as annotate_mod
		from red_pill.memento.ascension import parse_refine

		notes = _notes_pending(session_dir)
		if not notes:
			return {"skipped": True, "dir": dir_rel, "reason": "sin notas pendientes de ruta"}
		anns: List[Dict[str, Any]] = []
		for p in notes:
			_fm, body = parse_refine(p.read_text(encoding="utf-8"))
			anns.append({"text": body, "path": p})
		import red_pill.config as cfg

		th_work = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_WORK", 0.6))
		th_social = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_SOCIAL", 0.5))
		dead_zone = float(getattr(cfg, "MEMENTO_ANNOTATE_DEAD_ZONE", 0.05))
		with _notes_contract():
			annotate_mod._score_dual(transport, anns)
		resolved = 0
		for ann in anns:
			if "work_score" not in ann:
				continue
			work = float(ann["work_score"])
			social = float(ann["social_score"])
			route = annotate_mod._route(work, social, th_work, th_social, dead_zone)
			_update_note_scores(ann["path"], work, social, route if route else "none")
			resolved += int(route is not None)
		return {"dir": dir_rel, "notas_candidatas": len(notes), "resueltas": resolved}

	# target == "refines" (LEGACY): nunca sobre sesiones con notas
	if _has_annotate_notes(session_dir):
		return {"skipped": True, "dir": dir_rel, "reason": "tiene notas annotate — manda la nota"}
	if _has_category_score(session_dir):
		return {"skipped": True, "dir": dir_rel, "reason": "ya tiene category_score"}

	from red_pill.memento.agentic import refine_session

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

	refine_session(root, dir_rel, session_id or dir_rel, source or "?", sections, [], transport, 0.3)
	return {"dir": dir_rel, "refine_escritos": len(list((session_dir / "refine").glob("*.md"))) if (session_dir / "refine").is_dir() else 0}


def main() -> None:
	parser = argparse.ArgumentParser(description="Re-scoring notes-first (annotate) + reparación legacy de refine.")
	parser.add_argument("--list-pending", action="store_true", help="Imprime el JSON de sesiones candidatas")
	parser.add_argument("--process-one", action="store_true", help="Procesa UNA sesión (dir_rel desde RP_ELEMENT)")
	parser.add_argument("--target", choices=("notes", "refines"), default="notes", help="notes (default, annotate) | refines (legacy)")
	parser.add_argument("--limit", type=int, default=None, help="Batch/listado: solo las primeras N sesiones")
	parser.add_argument("--all", action="store_true", help="Batch: todo el árbol")
	args = parser.parse_args()

	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry

	root = get_memento_root()
	registry = MementoRegistry()

	if args.list_pending:
		print(json.dumps(list_pending(registry, root, target=args.target, limit=args.limit)))
		return

	if args.process_one or os.environ.get("RP_ELEMENT"):
		dir_rel = json.loads(os.environ["RP_ELEMENT"]) if os.environ.get("RP_ELEMENT") else args.process_one
		result = process_one(root, registry, dir_rel, target=args.target)
		print(f"[RESCORE] {result}")
		return

	# Batch (compatibilidad con el modo antiguo)
	stats = {"sesiones": 0, "resueltas": 0, "refine_escritos": 0, "errores": 0}
	processed = 0
	for dir_rel in list_pending(registry, root, target=args.target):
		if args.limit is not None and processed >= args.limit:
			break
		try:
			r = process_one(root, registry, dir_rel, target=args.target)
			if not r.get("skipped"):
				stats["sesiones"] += 1
				stats["resueltas"] += r.get("resueltas", 0)
				stats["refine_escritos"] += r.get("refine_escritos", 0)
				processed += 1
		except Exception as e:
			stats["errores"] += 1
			print(f"[RESCORE] error en {dir_rel}: {e}")
	print(f"[RESCORE] sesiones: {stats['sesiones']} | notas resueltas: {stats['resueltas']} | refine escritos: {stats['refine_escritos']} | errores: {stats['errores']}")


if __name__ == "__main__":
	main()
