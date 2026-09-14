#!/usr/bin/env python3
"""memento_purge_archive.py — purga de archive_memories (RFC-002 Fase 4 §6.8).

`archive_memories` dejó de ser fuente de reconstrucción (el árbol Memento tiene
100% de cobertura `raw/`; 2026-09-14) y su destino es la purga total CON backup
previo (decisión del operador, 2026-09-14). Dry-run por defecto; `--apply`
ejecuta: verificación de cobertura → snapshot backup → drop de la colección.

Uso:
    uv run python scripts/memento_purge_archive.py            # dry-run
    uv run python scripts/memento_purge_archive.py --apply    # snapshot + drop
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _raw_coverage(root: Path) -> dict:
	"""Cobertura de raw/ por sesión del registry (0-100%)."""
	from red_pill.memento.registry import MementoRegistry

	reg = MementoRegistry()
	total = 0
	with_raw = 0
	missing = []
	for source, sessions in reg.state["registry"].items():
		if not isinstance(sessions, dict):
			continue
		for sid, entry in sessions.items():
			dir_rel = entry.get("dir")
			if not dir_rel:
				continue
			total += 1
			raw_dir = Path(root) / dir_rel / "raw"
			has = raw_dir.is_dir() and any(raw_dir.iterdir())  # raw.jsonl + meta.json (no *.md)
			if has:
				with_raw += 1
			else:
				missing.append(f"{source}|{sid}")
	return {"total": total, "with_raw": with_raw, "missing": missing}


def main() -> None:
	parser = argparse.ArgumentParser(description="Purga de archive_memories (backup previo obligatorio).")
	parser.add_argument("--apply", action="store_true", help="Ejecuta snapshot backup + drop (por defecto: dry-run)")
	args = parser.parse_args()

	from red_pill.memento import get_memento_root
	from red_pill.memory import MemoryManager

	root = get_memento_root()
	cov = _raw_coverage(root)
	print(f"[PURGE] cobertura raw/: {cov['with_raw']}/{cov['total']} sesiones")
	if cov["missing"]:
		print("[PURGE] ABORT: hay sesiones sin raw/ — la reconstrucción desde raw/ NO es viable.")
		for m in cov["missing"][:10]:
			print(f"  - {m}")
		sys.exit(1)

	mm = MemoryManager()
	if not mm.client.collection_exists("archive_memories"):
		print("[PURGE] archive_memories no existe — nada que purgar.")
		return

	if not args.apply:
		print("[PURGE] DRY-RUN: se haría snapshot backup + drop de archive_memories (usa --apply).")
		return

	snap = mm.create_bunker_snapshot(["archive_memories"])
	desc = snap.get("archive_memories", "?")
	if str(desc).startswith("ERROR"):
		print(f"[PURGE] FALLO en el snapshot — NO se purga (backup previo obligatorio): {desc}")
		sys.exit(1)
	print(f"[PURGE] snapshot backup creado: {desc}")
	mm.client.delete_collection(collection_name="archive_memories")
	print("[PURGE] archive_memories purgada (drop total).")


if __name__ == "__main__":
	main()