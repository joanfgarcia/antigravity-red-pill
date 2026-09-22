#!/usr/bin/env python3
"""memento_ascend.py — ascenso estático del árbol Memento (refine/ + annotate/).

QUÉ ES / PARA QUÉ
	Promueve a Qdrant (`work_memories`/`social_memories`) los `refine/*.md` y
	`annotate/*.md` NO ascendidos cuya `significance` supera el gate de su categoría
	(`MEMENTO_GATE_MIN_SIGNIFICANCE_WORK` 0.6 / `_SOCIAL` 0.5). Las anotaciones con
	`dual_route: none` (ruido/zona muerta, MEM-006) **no** ascienden. Idempotente
	(upsert por `session_id`+`source_lines`+slug).

HISTORIA
	Nace del rebuild MEM-006 (2026-09-22): tras anotar el árbol hay que subir las
	notas a Qdrant. El paso nocturno `memento-reinforce` asciende por afinidad con
	la ventana reciente; el ascenso masivo post-rebuild es este job propio, que se
	encadena al rebuild con `--parent` (BLOCKED hasta que el rebuild completa).

USO
	uv run python scripts/memento_ascend.py --dry-run   # informa sin escribir (would_ascend)
	uv run python scripts/memento_ascend.py             # asciende
	Job: configs/jobs/memento_ascend_post_rebuild.yaml
"""

from __future__ import annotations

import argparse
import json

from red_pill.memento import get_memento_root
from red_pill.memento.ascension import ascend_by_threshold
from red_pill.memento.registry import MementoRegistry


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--dry-run", action="store_true", help="Informa (would_ascend) sin escribir en Qdrant.")
	parser.add_argument("--root", default=None, help="Raíz Memento (default: la configurada).")
	args = parser.parse_args()
	root = get_memento_root() if not args.root else args.root
	stats = ascend_by_threshold(root, MementoRegistry(), dry_run=args.dry_run)
	print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
