#!/usr/bin/env python3
"""Lista las sesiones pendientes de la ronda de re-destilado Memento como
`{"items": ["source:session_id", ...]}` en stdout (JSON).

Es la etapa FUENTE del fan-out por items del dag_job (RFC-JOBDAG-001 §4.6):
el DAG lee `items` del reporte y el paso siguiente expande una plantilla por
cada sesión. Reanudable por diseño: `pending_agentic` solo devuelve lo que
aún no se re-destiló en la ronda.
"""

import argparse
import json
import sys


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--redistill-round",
		metavar="ISO",
		help="Inicio de la ronda (ISO): solo las sesiones con distilled_at anterior a la ronda.",
	)
	args = parser.parse_args()

	from red_pill.memento import get_memento_root
	from red_pill.memento.agentic import pending_agentic
	from red_pill.memento.registry import MementoRegistry

	registry = MementoRegistry()
	root = get_memento_root()
	pending = pending_agentic(
		registry, root=root, force=True, redistill_since=args.redistill_round
	)
	items = [f"{src}:{sid}" for src, sid, _reason in pending]
	print(json.dumps({"items": items}, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	sys.exit(main())
