#!/usr/bin/env python3
"""Source stage of the nocturnal Memento pass fan-out (delta).

Lists the sessions the nightly agentic pass would process — EXACTLY the same
selection as `memento_agentic.py` WITHOUT `--target`:

	pending = pending_agentic(force=False)   # delta (no re-distill)
	order   = stale first                    # dead line refs first
	cap     = MEMENTO_AGENTIC_NIGHT_LIMIT     # same as the classic pass

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


def _message_count(registry, source: str, session_id: str) -> int:
	"""Tamaño de la sesión en mensajes (0 si no se puede leer)."""
	if registry is None:
		return 0
	try:
		entry = (registry.state.get("registry", {}).get(source, {}) or {}).get(session_id) or {}
		return int(entry.get("message_count") or 0)
	except Exception:
		return 0


def select_targets(pending, limit: int, msg_limit: int = 0, registry=None) -> list:
	"""Selección stale-first con DOS topes de coste (2026-11-03).

	`limit` acota sesiones (coste fijo: distill + annotate por sesión) y
	`msg_limit` acota mensajes (coste variable: el tamaño manda en el tiempo del
	LLM). Gana el que se cruce primero. La primera sesión entra siempre: un ítem
	mayor que el presupuesto no puede quedarse fuera para siempre.
	"""
	ordered = sorted(pending, key=lambda t: t[2] != "stale")
	chosen = []
	total_msgs = 0
	for source, session_id, reason in ordered:
		if limit > 0 and len(chosen) >= limit:
			break
		msgs = _message_count(registry, source, session_id)
		if msg_limit > 0 and chosen and total_msgs + msgs > msg_limit:
			break
		chosen.append((source, session_id, reason))
		total_msgs += msgs
	return [f"{src}:{sid}" for src, sid, _reason in chosen]


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
