#!/usr/bin/env python3
"""memento_probe_resynth.py — prueba de resíntesis+refinado con prompt corregido.

Copia UNA sesión de la muestra a /tmp/resintesis (árbol temporal, sin tocar lo
sembrado) y ejecuta distill_session + refine_session con el prompt corregido
(VOICE_RULE 1ª persona + category_score calibrado). Se usa como step_command del
job element_job `memento_probe.yaml` (RP_ELEMENT = dir_rel).

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

SAMPLE = "/tmp/muestra_100.json"
TMP = Path("/tmp/resintesis")
SEED = 11
COUNT = 25


def _selected() -> list:
	with open(SAMPLE) as f:
		muestra = json.load(f)
	random.seed(SEED)
	return random.sample(muestra, COUNT)


def process_one(dir_rel: str) -> dict:
	from red_pill.memento import get_memento_root
	from red_pill.memento.agentic import distill_session, http_transport, refine_session

	root = get_memento_root()
	src = Path(root) / dir_rel
	if not src.exists():
		return {"dir": dir_rel, "error": "no existe en el árbol real"}
	dst = TMP / dir_rel
	if dst.exists():
		shutil.rmtree(dst)
	shutil.copytree(src, dst)

	# session_id/source del registro de la muestra
	sid = source = dir_rel
	for s in _selected():
		if s[2] == dir_rel:
			source, sid, _ = s
			break

	sections = distill_session(TMP, dir_rel, sid, source, http_transport)
	refine_session(TMP, dir_rel, sid, source, sections, [], http_transport, 0.3)
	n_refine = len(list((dst / "refine").glob("*.md"))) if (dst / "refine").is_dir() else 0
	return {"dir": dir_rel, "distill": len(sections), "refine": n_refine}


def main() -> None:
	if len(sys.argv) > 1 and sys.argv[1] == "--list":
		print(json.dumps([s[2] for s in _selected()]))
		return
	dir_rel = json.loads(os.environ.get("RP_ELEMENT", "null"))
	if not dir_rel:
		print("RP_ELEMENT no definido (usa el job element_job)")
		sys.exit(2)
	print(f"[PROBE] {process_one(dir_rel)}")


if __name__ == "__main__":
	main()
