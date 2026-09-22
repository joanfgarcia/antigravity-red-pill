#!/usr/bin/env python3
"""memento_annotate.py — rebuild de anotaciones (MEM-006) sobre el árbol Memento.

QUÉ ES
	Ejecuta la etapa `annotate` sobre el árbol real, sesión a sesión: anotaciones
	idea-level extraídas del RAW (una sola compresión), con Bio de identidad (P0),
	dedup P1-A (hash + tokens), gate de calidad (género/identidad → no asciende),
	routing dual con zona muerta y rewrite de voz en 1ª persona.

PARA QUÉ
	Rebuild tras el fix del clasificador y la migración al modelo de anotaciones:
	reemplaza los `refine/` (re-resúmenes del summary, 52% duplicados de cuerpo) por
	`annotate/` (notas únicas, ≤600, voz de Aleth). La ascensión posterior sube los
	engramas (work/social) con `dual_route` + ejes.

HISTORIA (por qué nació)
	Sesión 2026-09-22 (MEM-006 + RFC-003). El diagnóstico midió: 9.424 refines con
	solo 4.556 cuerpos únicos; el refine leía summaries de distill (doble compresión)
	y producía re-resúmenes; el clasificador puntuaba textos compuestos (centro
	inestable). Los pilotos mostraron que anotar desde el raw corrige longitud
	(>600: 7,5%→~1,7%), duplicados (16,1%→1,9%) y, con el paso de rewrite, la voz
	(36%→100% 1ª persona en 5 sesiones). Evidencia en MEM-006 §6 (desk).

USO
	uv run python scripts/memento_annotate.py --list             # sesiones pendientes (JSON)
	uv run python scripts/memento_annotate.py --list --all       # ignora la frescura
	uv run python scripts/memento_annotate.py                    # procesa RP_ELEMENT (job)
	uv run python scripts/memento_annotate.py --root /tmp/x      # árbol alternativo (pruebas)

	Job: `configs/jobs/memento_annotate_rebuild.yaml` (element_job, checkpoint por
	sesión, pausable/reanudable). Frescura: una sesión ya anotada con el
	`annotate_prompt_version` vigente se omite (idempotente y reanudable).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from red_pill.memento import get_memento_root
from red_pill.memento.agentic import annotate_prompt_version, http_transport
from red_pill.memento.agentic.annotate import annotate_session


def _sessions(root: Path) -> list:
	dirs = sorted({p.parent.parent for p in root.rglob("memento/index.md")})
	out = []
	for d in dirs:
		rel = d.relative_to(root)
		if len(rel.parts) >= 3:
			out.append(str(rel))
	return out


def _fresh(root: Path, dir_rel: str) -> bool:
	ann = root / dir_rel / "annotate"
	files = sorted(ann.glob("*.md"))
	if not files:
		return False
	version = annotate_prompt_version()
	for f in files:
		txt = f.read_text(encoding="utf-8", errors="replace")
		if f"prompt_version: {version}" not in txt:
			return False
	return True


def pending(root: Path, force: bool = False) -> list:
	return [d for d in _sessions(root) if force or not _fresh(root, d)]


def process_one(root: Path, dir_rel: str, force: bool = False) -> dict:
	if not force and _fresh(root, dir_rel):
		return {"dir": dir_rel, "skipped": "fresh"}
	parts = Path(dir_rel).parts
	source = parts[1] if len(parts) > 1 else "unknown"
	session_id = parts[2] if len(parts) > 2 else dir_rel
	max_sig = annotate_session(root, dir_rel, session_id, source, http_transport, voice_rewrite=True)
	n = len(list((root / dir_rel / "annotate").glob("*.md")))
	return {"dir": dir_rel, "anotaciones": n, "max_significance": round(float(max_sig), 2)}


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--list", action="store_true", help="Imprime las sesiones pendientes (JSON).")
	parser.add_argument("--all", action="store_true", help="Ignora la frescura (re-anota todo).")
	parser.add_argument("--root", type=Path, default=None, help="Raíz Memento (default: la configurada).")
	args = parser.parse_args()
	root = args.root or get_memento_root()

	if args.list:
		print(json.dumps([{"dir": d} for d in pending(root, force=args.all)], ensure_ascii=False))
		return
	raw = os.environ.get("RP_ELEMENT")
	if not raw:
		print("RP_ELEMENT no definido (usa el job element_job) o pasa --list")
		sys.exit(2)
	el = json.loads(raw)
	try:
		res = process_one(root, str(el["dir"]), force=args.all)
	except Exception as e:
		from red_pill.memento.agentic.runner import _is_llm_connection_error

		if _is_llm_connection_error(e):
			print(f"[DEFER] LLM no disponible: {e}")
			sys.exit(int(os.environ.get("RP_DEFER_EXIT_CODE", 77)))
		raise
	print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
	main()
