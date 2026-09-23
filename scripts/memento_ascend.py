#!/usr/bin/env python3
"""memento_ascend.py — ascenso estático del árbol Memento (refine/ + annotate/) y sustitución legacy.

QUÉ ES / PARA QUÉ
	Promueve a Qdrant (`work_memories`/`social_memories`) los `refine/*.md` y
	`annotate/*.md` NO ascendidos cuya `significance` supera el gate de su categoría
	(`MEMENTO_GATE_MIN_SIGNIFICANCE_WORK` 0.6 / `_SOCIAL` 0.5). Las anotaciones con
	`dual_route: none` (ruido/zona muerta, MEM-006) **no** ascienden. Idempotente
	(upsert por `session_id`+`source_lines`+slug).

	`--replace-legacy` (MEM-006): sustituye la capa legacy por las notas — por cada
	sesión con notas ascendibles: (1) normaliza el `session_id` de las notas al
	canónico del registry, (2) borra de Qdrant los engramas legacy de esa sesión
	(`origin=memento` + `refine_ref: …/refine/…`), (3) asciende las notas, (4) sella
	los `refine/` como `replaced_by_annotate` (no resucitables por el flujo normal).
	Convergente: re-ejecutarlo es no-op para sesiones ya sustituidas.

HISTORIA
	Nace del rebuild MEM-006 (2026-09-22): tras anotar el árbol hay que subir las
	notas a Qdrant. El paso nocturno `memento-reinforce` asciende por afinidad con
	la ventana reciente; el ascenso/sustitución masivo post-rebuild es este job,
	encadenado al rebuild con `--parent` (BLOCKED hasta que el rebuild completa).
	La sustitución llegó tras medir el solape: 52/95 sesiones anotadas ya tenían
	1.656 engramas legacy (refine) en Qdrant — mantener ambos duplicaba la sesión.

USO
	uv run python scripts/memento_ascend.py --dry-run                    # informa (would_ascend)
	uv run python scripts/memento_ascend.py                              # asciende
	uv run python scripts/memento_ascend.py --replace-legacy --dry-run   # informe de sustitución
	uv run python scripts/memento_ascend.py --replace-legacy             # sustituye + asciende
	Job: configs/jobs/memento_ascend_post_rebuild.yaml
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from red_pill.memento import get_memento_root
from red_pill.memento.ascension import ascend_by_threshold, parse_refine
from red_pill.memento.registry import MementoRegistry

COLLECTIONS = ("work_memories", "social_memories")


def _gate(route: str) -> float:
	import red_pill.config as cfg

	if route == "work":
		return float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_WORK", 0.6))
	return float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_SOCIAL", 0.5))


def _registry_dir_map() -> Dict[str, str]:
	"""dir_rel → session_id canónico (del registry)."""
	mapping: Dict[str, str] = {}
	for _source, sessions in (MementoRegistry().state.get("registry") or {}).items():
		if not isinstance(sessions, dict):
			continue
		for sid, entry in sessions.items():
			dir_rel = str((entry or {}).get("dir") or "")
			if dir_rel:
				mapping[dir_rel] = sid
	return mapping


def _ascendable_sessions(root: Path) -> Dict[str, Dict[str, Any]]:
	"""dir_rel → {sid, notes, files} de sesiones con ≥1 nota ascendible (work/social ≥ gate)."""
	out: Dict[str, Dict[str, Any]] = {}
	dir_map = _registry_dir_map()
	for p in sorted(root.rglob("annotate/*.md")):
		txt = p.read_text(encoding="utf-8", errors="replace")
		fm, _body = parse_refine(txt)
		if fm.get("ascended") == "true":
			continue
		route = str(fm.get("dual_route") or "none").strip().lower()
		if route not in ("work", "social"):
			continue
		try:
			sig = float(fm.get("significance", 0) or 0)
		except (TypeError, ValueError):
			sig = 0.0
		if sig < _gate(route):
			continue
		rel = p.relative_to(root).parts
		dir_rel = str(Path(*rel[:3]))
		entry = out.setdefault(dir_rel, {"sid": dir_map.get(dir_rel, ""), "notes": 0, "files": []})
		entry["notes"] += 1
		entry["files"].append(p)
		if not entry["sid"]:
			entry["sid"] = str(fm.get("session_id") or "")
	return out


def _legacy_points(memory_manager: Any, sids: Set[str]) -> Dict[str, Dict[str, List[Any]]]:
	"""Puntos legacy (refine) por colección y session_id."""
	out: Dict[str, Dict[str, List[Any]]] = {c: {} for c in COLLECTIONS}
	for coll in COLLECTIONS:
		offset = None
		while True:
			pts, offset = memory_manager.client.scroll(collection_name=coll, limit=512, offset=offset, with_payload=True, with_vectors=False)
			for pt in pts:
				pl = pt.payload or {}
				sid = str(pl.get("session_id") or "")
				if pl.get("origin") == "memento" and "/refine/" in str(pl.get("refine_ref") or "") and sid in sids:
					out[coll].setdefault(sid, []).append(pt.id)
			if offset is None:
				break
	return out


def replace_legacy(root: Path, dry_run: bool = False) -> Dict[str, Any]:
	"""Sustitución legacy→notas por sesión (normaliza ids, borra refines, asciende notas, sella)."""
	from red_pill.memento.ascension import _stamp_refine
	from red_pill.memory import MemoryManager

	sessions = _ascendable_sessions(root)
	sids = {v["sid"] for v in sessions.values() if v["sid"]}
	mm = MemoryManager()
	legacy = _legacy_points(mm, sids)
	legacy_n = sum(len(ids) for by_sid in legacy.values() for ids in by_sid.values())
	legacy_sids = {sid for by_sid in legacy.values() for sid in by_sid}

	norm = 0
	for info in sessions.values():
		if not info["sid"]:
			continue
		for f in info["files"]:
			fm, _ = parse_refine(f.read_text(encoding="utf-8", errors="replace"))
			if str(fm.get("session_id") or "") != info["sid"]:
				norm += 1
				if not dry_run:
					_stamp_refine(f, {"session_id": info["sid"]})

	stats: Dict[str, Any] = {
		"sesiones_ascendibles": len(sessions),
		"notas_ascendibles": sum(v["notes"] for v in sessions.values()),
		"session_id_normalizados": norm,
		"legacy_engramas": legacy_n,
		"legacy_sesiones": len(legacy_sids),
		"dry_run": dry_run,
	}
	if dry_run:
		stats["ascenso"] = ascend_by_threshold(root, MementoRegistry(), dry_run=True)
		return stats

	deleted = 0
	for coll, by_sid in legacy.items():
		ids = [pt_id for group in by_sid.values() for pt_id in group]
		for i in range(0, len(ids), 256):
			batch = ids[i : i + 256]
			mm.client.delete(collection_name=coll, points_selector=batch)
			deleted += len(batch)

	asc = ascend_by_threshold(root, MementoRegistry())

	marked = 0
	stamp_time = datetime.now(timezone.utc).isoformat()
	for dir_rel, info in sessions.items():
		if info["sid"] not in legacy_sids:
			continue
		for f in sorted((root / dir_rel / "refine").glob("*.md")) if (root / dir_rel / "refine").is_dir() else []:
			_stamp_refine(f, {"replaced_by_annotate": True, "replaced_at": stamp_time})
			marked += 1

	stats.update({"legacy_borrados": deleted, "refines_sellados": marked, "ascenso": asc})
	return stats


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--dry-run", action="store_true", help="Informa sin escribir en Qdrant.")
	parser.add_argument("--replace-legacy", action="store_true", help="Sustituye la capa legacy (refine) por las notas.")
	parser.add_argument("--root", default=None, help="Raíz Memento (default: la configurada).")
	args = parser.parse_args()
	root = get_memento_root() if not args.root else args.root
	if args.replace_legacy:
		stats = replace_legacy(root, dry_run=args.dry_run)
	else:
		stats = ascend_by_threshold(root, MementoRegistry(), dry_run=args.dry_run)
	print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
