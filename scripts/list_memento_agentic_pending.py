#!/usr/bin/env python3
"""Source stage of the nocturnal Memento pass fan-out (delta).

Lists the sessions the nightly agentic pass would process — EXACTLY the same
selection as `memento_agentic.py` WITHOUT `--target`:

	pending = pending_agentic(force=False)   # delta (no re-distill)
	order   = stale first                    # dead line refs first
	cap     = MEMENTO_AGENTIC_NIGHT_LIMIT     # misma política que el pase clásico
	cap_msgs = MEMENTO_AGENTIC_NIGHT_MSG_LIMIT #   (la selección vive en agentic/selection.py)

Emits `{"items": ["source:session_id", ...]}` on stdout (the fan-out source
contract of the dag_job item fan-out, RFC-JOBDAG-001 §4.6). This way EACH session
is a DAG step → the job progress advances per session (RFC-JOBDAG-002) instead of
staying stuck while a single command loops over it internally.

NOT the re-distill `list_memento_pending.py`: that one uses `force=True` and no
cap (reprocesses everything); this one mirrors the daily DELTA.
"""

import argparse
import json
import sys


def select_targets(pending, limit: int, msg_limit: int = 0, registry=None) -> list:
	"""Selección stale-first con DOS topes de coste (fuente: `agentic.selection`).

	Delegado a `red_pill.memento.agentic.selection`: la política vive en UN sitio
	para que el pase clásico (`memento_agentic.py` sin `--target`) no pueda divergir
	del discover — que es exactamente lo que pasaba con el tope por mensajes recién
	añadido (el `discover` lo aplicaba, el pase clásico no).
	"""
	from red_pill.memento.agentic.selection import select_targets as _select

	return [f"{src}:{sid}" for src, sid, _reason in _select(pending, limit, msg_limit=msg_limit, registry=registry)]


def main() -> int:
	"""Emit the fan-out source item list as JSON on stdout."""
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
	msg_limit = int(getattr(cfg, "MEMENTO_AGENTIC_NIGHT_MSG_LIMIT", 0))
	items = select_targets(pending, limit, msg_limit=msg_limit, registry=registry)
	print(
		json.dumps(
			{"items": items, "total": len(pending), "selected": len(items), "left": max(0, len(pending) - len(items))},
			ensure_ascii=False,
		)
	)
	return 0


if __name__ == "__main__":
	sys.exit(main())
