#!/usr/bin/env python3
"""Cola de arreglo: las N sesiones PEOR puntuadas que aún no se han reprocesado.

Lee el listado de `memento_audit.py` (o lo recalcula), descarta las que ya están
en el libro de procesadas y emite el array JSON que consume el `element_job`.

Autocorrectiva por construcción: al reprocesar una sesión su score baja (o
desaparece del listado), así que la siguiente pasada propone las siguientes sin
necesidad de mantener un índice a mano. El libro (`memento_fix_done.jsonl`) está
para lo otro: que una sesión que SIGUE puntuando alto no se repita en bucle.

Uso:
	python scripts/memento_fix_queue.py --n 2 --min-score 20
	python scripts/memento_fix_queue.py --n 5 --min-score 12 --all-sources
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from memento_audit import auditar_sesion  # noqa: E402


def _libro(path: Path) -> set:
	if not path.exists():
		return set()
	hechas = set()
	for line in path.read_text(encoding="utf-8").splitlines():
		try:
			hechas.add(json.loads(line)["session"])
		except Exception:
			continue
	return hechas


def main() -> None:
	ap = argparse.ArgumentParser(description="Cola de reprocesado Memento")
	ap.add_argument("--n", type=int, default=2, help="cuántas sesiones propone esta tanda")
	ap.add_argument("--min-score", type=int, default=20, help="score mínimo para entrar")
	ap.add_argument("--root", default=None)
	ap.add_argument("--ledger", default=None, help="libro de procesadas (JSONL)")
	ap.add_argument("--source", default="opencode", help="prefijo de fuente a proponer ('' = todas)")
	args = ap.parse_args()

	if args.root:
		root = Path(args.root)
	else:
		from red_pill.memento import get_memento_root

		root = get_memento_root()
	# Soberanía de rutas (test_no_hardcoded_paths): nada de `~` cableado. El
	# libro vive en el state dir del Búnker, resuelto por core/paths.
	from red_pill.core.paths import get_state_dir

	ledger = Path(args.ledger) if args.ledger else get_state_dir() / "memento_fix_done.jsonl"
	hechas = _libro(ledger)

	filas = []
	for d in sorted(root.glob("*/*/*")):
		if not d.is_dir() or not ((d / "distill").is_dir() and (d / "annotate").is_dir()):
			continue
		if args.source and args.source not in d.parent.name:
			continue
		try:
			fila = auditar_sesion(d, root)
		except Exception:
			continue
		if fila["score"] < args.min_score or fila["session"] in hechas:
			continue
		filas.append(fila)

	filas.sort(key=lambda r: -r["score"])
	elegidas = filas[: args.n]

	# El `target` es lo que entiende `memento_agentic.py --target`: fuente:id.
	# En el árbol, la carpeta es `<fuente>/<fuente>-<id>` (p.ej. opencode/opencode-ses_x).
	elementos = []
	for f in elegidas:
		fuente = f["dir"].split("/")[1]
		carpeta = f["dir"].split("/")[2]
		sid = carpeta[len(fuente) + 1 :] if carpeta.startswith(fuente + "-") else carpeta
		elementos.append({"target": f"{fuente}:{sid}", "phase": "both", "score": f["score"]})

	print(json.dumps(elementos))
	if not elementos:
		print(f"[fix-queue] nada que proponer (min-score={args.min_score}, hechas={len(hechas)})", file=sys.stderr)


if __name__ == "__main__":
	main()
