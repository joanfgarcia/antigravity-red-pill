#!/usr/bin/env python3
"""memento_probe_resynth.py — prueba de la etapa ANNOTATE (MEM-006).

Copia UNA sesión de la muestra a /tmp (árbol temporal, sin tocar el sembrado) y
ejecuta la etapa real `annotate_session`: anotaciones idea-level desde el RAW con
Bio de identidad, dedup P1-A, gate de calidad, routing dual y rewrite de voz. Se
usa como step_command del job element_job `memento_probe.yaml` (RP_ELEMENT = dir_rel).

Historia: era la prueba del refine legacy (distill→refine con prompt corregido);
desde la retirada del refine (2026-09-22) prueba el camino que SÍ corre en
producción (annotate). El refine queda solo para repair/reinforce/rescore.

Uso:
	uv run python scripts/memento_probe_resynth.py --list
	uv run python scripts/memento_probe_resynth.py  # procesa RP_ELEMENT
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
from pathlib import Path

TMP = Path("/tmp/resintesis")
SEED = 11
COUNT = 25


def _selected() -> list:
	"""Muestra determinista del árbol (sin ficheros /tmp efímeros): N sesiones."""
	from red_pill.memento import get_memento_root

	root = Path(get_memento_root())
	dirs = sorted(
		{
			str(p.parent.parent.relative_to(root))
			for p in root.rglob("memento/index.md")
			if len(p.parent.parent.relative_to(root).parts) >= 3
		}
	)
	rnd = random.Random(SEED)
	return rnd.sample(dirs, min(COUNT, len(dirs)))


def process_one(dir_rel: str) -> dict:
	from red_pill.memento import get_memento_root
	from red_pill.memento.agentic import annotate_session, http_transport

	root = get_memento_root()
	src = Path(root) / dir_rel
	if not src.exists():
		return {"dir": dir_rel, "error": "no existe en el árbol real"}
	dst = TMP / dir_rel
	if dst.exists():
		shutil.rmtree(dst)
	shutil.copytree(src, dst)

	parts = Path(dir_rel).parts
	source = parts[1] if len(parts) > 1 else "unknown"
	sid = parts[2] if len(parts) > 2 else dir_rel

	max_sig = annotate_session(TMP, dir_rel, sid, source, http_transport, voice_rewrite=True)
	n_notes = len(list((dst / "annotate").glob("*.md"))) if (dst / "annotate").is_dir() else 0
	return {"dir": dir_rel, "anotaciones": n_notes, "max_significance": round(float(max_sig), 2)}


def main() -> None:
	if len(sys.argv) > 1 and sys.argv[1] == "--list":
		print(json.dumps(_selected()))
		return
	dir_rel = json.loads(os.environ.get("RP_ELEMENT", "null"))
	if not dir_rel:
		print("RP_ELEMENT no definido (usa el job element_job)")
		sys.exit(2)
	print(f"[PROBE] {process_one(dir_rel)}")


if __name__ == "__main__":
	main()
