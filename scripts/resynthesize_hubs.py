#!/usr/bin/env python3
"""Re-síntesis jerárquica de hubs truncados (map-reduce).

QUÉ ES
	Inventaría las sesiones cuyo prompt de hub supera `SLEEP_MAX_HUB_INPUT_CHARS`
	(`--list`) y re-sintetiza su hub con el map-reduce de `synthesize_hub_v2`
	(`--run`, un elemento). Sustituye el truncado silencioso por hubs parciales
	+ reducción jerárquica, y consume el marcador legado `hub_rebuild_pending`.

USO
    .venv/bin/python scripts/resynthesize_hubs.py --list
    .venv/bin/python scripts/resynthesize_hubs.py --dry-run --collection work_memories --session <sid>
    RP_ELEMENT='{"collection":"work_memories","session_id":"..."}' \
      .venv/bin/python scripts/resynthesize_hubs.py --run

    Job: `configs/jobs/hubs_resynthesize.yaml` (element_job, un step por sesión,
    pausable/reanudable, fail-soft con skip_exit_code).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from red_pill.memory import MemoryManager  # noqa: E402
from red_pill.metabolism.hub_synthesis import (  # noqa: E402
	find_oversized_sessions,
	load_session_members,
	members_to_chunks,
	resynthesize_session,
)


def _element_from_args(args: argparse.Namespace) -> dict:
	if args.collection and args.session:
		return {"collection": args.collection, "session_id": args.session}
	raw = os.environ.get("RP_ELEMENT")
	if not raw:
		print("[ERROR] define RP_ELEMENT o pasa --collection/--session", file=sys.stderr)
		raise SystemExit(2)
	try:
		return json.loads(raw)
	except json.JSONDecodeError as e:
		print(f"[ERROR] RP_ELEMENT no es JSON válido: {e}", file=sys.stderr)
		raise SystemExit(2)


def main() -> None:
	parser = argparse.ArgumentParser(description="Re-síntesis jerárquica de hubs truncados")
	parser.add_argument("--list", action="store_true", help="Imprime las sesiones afectadas (JSON).")
	parser.add_argument("--all", action="store_true", help="Con --list, incluye también las ya re-sintetizadas.")
	parser.add_argument("--run", action="store_true", help="Re-sintetiza el elemento de RP_ELEMENT.")
	parser.add_argument("--dry-run", action="store_true", help="Sintetiza sin escribir (smoke test).")
	parser.add_argument("--collection", help="work_memories | social_memories")
	parser.add_argument("--session", help="session_id")
	parser.add_argument("--limit", type=int, default=0, help="Acota --list (0 = todas).")
	args = parser.parse_args()

	memory = MemoryManager()

	if args.list:
		rows = find_oversized_sessions(memory, only_pending=not args.all)
		if args.limit and args.limit > 0:
			rows = rows[: args.limit]
		print(json.dumps(rows, ensure_ascii=False))
		return

	if not args.run and not args.dry_run:
		parser.error("indica --list, --run o --dry-run")

	element = _element_from_args(args)
	collection = str(element.get("collection") or "")
	session_id = str(element.get("session_id") or "")
	if not collection or not session_id:
		print("[ERROR] el elemento necesita 'collection' y 'session_id'", file=sys.stderr)
		raise SystemExit(2)

	if args.dry_run:
		from red_pill.metabolism.distiller import render_hub_items, synthesize_hub_v2

		members = load_session_members(memory, collection, session_id)
		chunks = members_to_chunks(members)
		hub = synthesize_hub_v2(chunks)
		print(
			json.dumps(
				{
					"collection": collection,
					"session_id": session_id,
					"members": len(members),
					"input_chars": len(render_hub_items(chunks)),
					"hierarchical": bool(hub.get("hierarchical")),
					"partition_count": int(hub.get("partition_count") or 0),
					"map_reduce_levels": int(hub.get("map_reduce_levels") or 0),
					"truncated": bool(hub.get("truncated")),
					"is_fallback": bool(hub.get("_is_fallback")),
					"summary_chars": len(str(hub.get("summary") or "")),
					"title": str(hub.get("title") or "")[:160],
				},
				ensure_ascii=False,
			)
		)
		return

	result = resynthesize_session(memory, collection, session_id, force=True)
	print(json.dumps({"collection": collection, "session_id": session_id, "result": result}, ensure_ascii=False))
	if result == "failed":
		# Fail-soft del element_job: registra y sigue con el resto.
		code = int(os.environ.get("RP_SKIP_EXIT_CODE", "0") or 0)
		raise SystemExit(code or 1)


if __name__ == "__main__":
	main()
