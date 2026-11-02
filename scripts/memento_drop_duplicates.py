#!/usr/bin/env python3
"""Retira de Memento las sesiones `memory_queue` que DUPLICAN una de opencode.

Medido el 2026-11-02: 95 de las 305 sesiones de `memory_queue` tenían
`session_id` explícito y **las 95 eran duplicados exactos** de una sesión de
opencode (mismo `opencode:ses_x`), con su raw ya guardado por el provider. Eran
doble coste: doble destilado y doble anotación sobre la misma conversación.

No se borra nada: los directorios se **mueven** a `memento_archive/duplicados/`
y sus entradas salen del registro. El contenido sigue en la sesión de opencode.

Uso:
	scripts/memento_drop_duplicates.py --dry-run
	scripts/memento_drop_duplicates.py --apply
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEST = Path.home() / ".local" / "share" / "red-pill" / "memento_archive" / "duplicados"


def find_duplicates(registry) -> list:
	"""[(source, session_id, dir_rel)] de memory_queue duplicando una sesión de opencode."""
	out = []
	oc = registry.sessions_of("opencode")
	for session_id, entry in registry.sessions_of("memory_queue").items():
		parts = session_id.split(":")
		if len(parts) < 3 or not parts[2].startswith("ses_"):
			continue
		if f"opencode:{parts[2]}" not in oc:
			continue
		out.append(("memory_queue", session_id, str(entry.get("dir") or "")))
	return out


def main() -> int:
	parser = argparse.ArgumentParser(description="Retira duplicados de memory_queue en Memento")
	parser.add_argument("--dry-run", action="store_true")
	parser.add_argument("--apply", action="store_true")
	args = parser.parse_args()
	if not (args.dry_run or args.apply):
		parser.error("indica --dry-run o --apply")

	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry

	root = Path(get_memento_root())
	registry = MementoRegistry()
	dups = find_duplicates(registry)
	print(f"[duplicados] {len(dups)} sesión(es) memory_queue con gemela en opencode{' (dry-run)' if args.dry_run else ''}")
	if args.dry_run:
		for _source, session_id, rel in dups[:10]:
			print(f"  {session_id[:60]}  dir={rel}")
		return 0

	moved = 0
	for _source, session_id, rel in dups:
		if rel and (root / rel).exists():
			dest = DEST / rel
			dest.parent.mkdir(parents=True, exist_ok=True)
			shutil.move(str(root / rel), str(dest))
			moved += 1
		registry.state["registry"]["memory_queue"].pop(session_id, None)
	registry.state["stats"]["total_sessions"] = int(registry.state["stats"].get("total_sessions", 0)) - len(dups)
	registry.save()
	try:
		from red_pill.memento.indexes import rebuild_indexes

		rebuild_indexes(root, registry)
	except Exception as exc:
		print(f"[duplicados] índices no reconstruidos: {exc}")
	print(f"[duplicados] retiradas {len(dups)} entradas · {moved} directorio(s) movidos a {DEST}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
