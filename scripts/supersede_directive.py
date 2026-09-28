#!/usr/bin/env python3
"""Marca una directiva como reemplazada por otra (campo `superseded`).

Sin borrar engramas: escribe `superseded = <new_id>` en la directiva vieja para
que `read_core_directives` deje de cargarla. Dry-run por defecto.

Uso:
	uv run python scripts/supersede_directive.py --old <id> --new <id>          # dry-run
	uv run python scripts/supersede_directive.py --old <id> --new <id> --apply
"""

from __future__ import annotations

import argparse
import sys

from red_pill.core.directives import mark_superseded
from red_pill.memory import MemoryManager


def main() -> int:
	ap = argparse.ArgumentParser(description="Marca una directiva como superseded (sin borrar).")
	ap.add_argument("--old", required=True, help="id de la directiva a reemplazar")
	ap.add_argument("--new", required=True, help="id del engrama que la reemplaza")
	ap.add_argument("--apply", action="store_true", help="Ejecuta (por defecto: dry-run)")
	args = ap.parse_args()

	mm = MemoryManager()
	pts = mm.client.retrieve("directive_memories", ids=[args.old], with_payload=True)
	if not pts:
		print(f"[SUPERSEDE] id no encontrado: {args.old}")
		return 1
	payload = pts[0].payload or {}
	print(f"[SUPERSEDE] old={args.old}")
	print(f"   content: {str(payload.get('content'))[:100]}")
	print(f"   immune={payload.get('immune')} superseded={payload.get('superseded')}")
	print(f"[SUPERSEDE] pasaría a superseded={args.new}")

	if not args.apply:
		print("[SUPERSEDE] DRY-RUN — usa --apply para escribir.")
		return 0
	ok = mark_superseded(mm, args.old, args.new)
	print(f"[SUPERSEDE] {'OK' if ok else 'FALLÓ'} — {args.old} → superseded={args.new}")
	return 0 if ok else 1


if __name__ == "__main__":
	sys.exit(main())
