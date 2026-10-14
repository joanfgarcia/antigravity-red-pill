#!/usr/bin/env python3
"""Etapa FUENTE del fan-out del pase Memento nocturno (delta).

Lista las sesiones que el pase agéntico nocturno procesaría — EXACTAMENTE la
misma selección que `memento_agentic.py` SIN `--target`:

  pending = pending_agentic(force=False)   # delta (no re-destilado)
  orden   = stale primero                  # line refs muertos primero
  tope    = MEMENTO_AGENTIC_NIGHT_LIMIT     # igual que el pase clásico

Emite `{"items": ["source:session_id", ...]}` en stdout (contrato de la fuente
del fan-out por items del dag_job, RFC-JOBDAG-001 §4.6). Así CADA sesión es un
step del DAG → el progreso del job avanza por sesión (RFC-JOBDAG-002) en vez de
quedar clavado mientras un único comando recorre el bucle por dentro.

NO es el `list_memento_pending.py` del re-destilado: aquel usa `force=True` y sin
tope (reprocesa todo); este espeja el DELTA diario.
"""

import argparse
import json
import sys


def select_targets(pending, limit: int) -> list:
	"""Selección espejo de `memento_agentic.py` sin --target: stale primero + tope."""
	ordered = sorted(pending, key=lambda t: t[2] != "stale")
	return [f"{src}:{sid}" for src, sid, _reason in ordered[:limit]]


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--limit", type=int, default=None, help="Máx. sesiones (def: MEMENTO_AGENTIC_NIGHT_LIMIT)")
	args = parser.parse_args()

	import red_pill.config as cfg
	from red_pill.memento import get_memento_root
	from red_pill.memento.agentic import pending_agentic
	from red_pill.memento.registry import MementoRegistry

	registry = MementoRegistry()
	root = get_memento_root()
	pending = pending_agentic(registry, root=root, force=False, redistill_since=None)
	limit = args.limit if args.limit is not None else int(getattr(cfg, "MEMENTO_AGENTIC_NIGHT_LIMIT", 20))
	print(json.dumps({"items": select_targets(pending, limit)}, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	sys.exit(main())
