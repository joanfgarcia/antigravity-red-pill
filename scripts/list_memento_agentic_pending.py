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


def select_targets(pending, limit: int) -> list:
	"""Selection mirroring `memento_agentic.py` without --target: stale first + cap."""
	ordered = sorted(pending, key=lambda t: t[2] != "stale")
	return [f"{src}:{sid}" for src, sid, _reason in ordered[:limit]]


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
	print(json.dumps({"items": select_targets(pending, limit)}, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	sys.exit(main())
