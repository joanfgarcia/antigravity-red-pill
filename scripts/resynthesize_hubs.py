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
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from red_pill.memory import MemoryManager  # noqa: E402
from red_pill.metabolism.hub_synthesis import (  # noqa: E402
	backup_hub_payload,
	find_oversized_sessions,
	find_stale_hubs,
	load_session_members,
	members_to_chunks,
	promote_compact_hub,
	reconcile_hub_blocks,
	restore_hub_payload,
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
	parser.add_argument(
		"--list-stale",
		action="store_true",
		help="Inventario READ-ONLY de hubs fuera del contrato vigente (v<3 o summary>hard). D-11: listar, no migrar.",
	)
	parser.add_argument("--eligible", action="store_true", help="Con --list-stale, omite los hubs marcados hub_migration_blocked.")
	parser.add_argument(
		"--mark-blocked",
		action="store_true",
		help="Reconcilia hub_migration_blocked/hub_members_count de todos los hubs (aplica; con --dry-run solo informa).",
	)
	parser.add_argument(
		"--promote-compact",
		action="store_true",
		help="Promociona a v3 (metadata, sin tocar content) hubs legacy compactos que no logran re-sintetizarse.",
	)
	parser.add_argument("--ensure-indexes", action="store_true", help="Crea los índices de payload hub→miembro (idempotente).")
	parser.add_argument("--restore", metavar="JSON", help="Revierte un hub desde un backup (payload+vector+marcas de miembros).")
	parser.add_argument("--backup-dir", help="Directorio de backups (default: state/backups/hub_payloads_YYYYMMDD).")
	parser.add_argument("--no-backup", action="store_true", help="Con --run, NO escribe backup previo (no recomendado).")
	parser.add_argument("--all", action="store_true", help="Con --list, incluye también las ya re-sintetizadas.")
	parser.add_argument("--run", action="store_true", help="Re-sintetiza el elemento de RP_ELEMENT.")
	parser.add_argument("--dry-run", action="store_true", help="Sintetiza sin escribir (smoke test).")
	parser.add_argument("--collection", help="work_memories | social_memories")
	parser.add_argument("--session", help="session_id")
	parser.add_argument("--limit", type=int, default=0, help="Acota --list (0 = todas).")
	args = parser.parse_args()

	memory = MemoryManager()

	if args.ensure_indexes:
		for coll in ("work_memories", "social_memories"):
			memory.storage.ensure_payload_indexes(coll)
		print(json.dumps({"ensure_indexes": ["work_memories", "social_memories"], "ok": True}))
		return

	if args.mark_blocked:
		rows = reconcile_hub_blocks(memory, apply=not args.dry_run)
		blocked = sum(1 for row in rows if row["blocked"])
		changed = sum(1 for row in rows if row["changed"])
		print(
			json.dumps(
				{
					"dry_run": bool(args.dry_run),
					"hubs": len(rows),
					"blocked": blocked,
					"eligible": len(rows) - blocked,
					"changed": changed,
					"reasons": {
						"no_members": sum(1 for row in rows if row["reason"] == "no_members"),
						"singleton": sum(1 for row in rows if row["reason"] == "singleton"),
					},
					"rows": rows,
				},
				ensure_ascii=False,
			)
		)
		return

	if args.promote_compact:
		rows = find_stale_hubs(memory)
		results = []
		for row in rows:
			if row.get("hub_migration_blocked"):
				continue
			result = promote_compact_hub(memory, row["collection"], row["session_id"], apply=not args.dry_run)
			results.append(
				{
					"collection": row["collection"],
					"hub_id": row["hub_id"],
					"session_id": row["session_id"],
					"hub_synth_version": row["hub_synth_version"],
					"content_chars": row["content_chars"],
					"result": result,
				}
			)
		counts = {key: sum(1 for r in results if r["result"] == key) for key in ("promoted", "would_promote", "over_hard", "already", "missing")}
		print(json.dumps({"dry_run": bool(args.dry_run), "counts": counts, "results": results}, ensure_ascii=False))
		return

	if args.list_stale:
		rows = find_stale_hubs(memory)
		if args.eligible:
			rows = [row for row in rows if not row.get("hub_migration_blocked")]
		if args.limit and args.limit > 0:
			rows = rows[: args.limit]
		print(json.dumps(rows, ensure_ascii=False))
		return

	if args.list:
		rows = find_oversized_sessions(memory, only_pending=not args.all)
		if args.limit and args.limit > 0:
			rows = rows[: args.limit]
		print(json.dumps(rows, ensure_ascii=False))
		return

	if args.restore:
		try:
			ok = restore_hub_payload(memory, args.restore)
			print(json.dumps({"restored": args.restore, "ok": ok}, ensure_ascii=False))
		except Exception as exc:
			print(f"[ERROR] restore falló: {exc}", file=sys.stderr)
			raise SystemExit(1)
		return

	if not args.run and not args.dry_run:
		parser.error("indica --list, --list-stale, --mark-blocked, --promote-compact, --ensure-indexes, --restore, --run o --dry-run")

	element = _element_from_args(args)
	collection = str(element.get("collection") or "")
	session_id = str(element.get("session_id") or "")
	if not collection or not session_id:
		print("[ERROR] el elemento necesita 'collection' y 'session_id'", file=sys.stderr)
		raise SystemExit(2)

	if args.dry_run:
		import time as _time

		from red_pill.metabolism.distiller import render_hub_items, synthesize_hub_v2

		members = load_session_members(memory, collection, session_id)
		members.sort(key=lambda m: (float((m[1] or {}).get("created_at") or 0), str(m[0])))
		chunks = members_to_chunks(members)
		t0 = _time.time()
		hub = synthesize_hub_v2(chunks, cache_namespace=f"{collection}:{session_id}")
		elapsed = round(_time.time() - t0, 1)
		print(
			json.dumps(
				{
					"collection": collection,
					"session_id": session_id,
					"members": len(members),
					"input_chars": len(render_hub_items(chunks)),
					"elapsed_s": elapsed,
					"hierarchical": bool(hub.get("hierarchical")),
					"partition_count": int(hub.get("partition_count") or 0),
					"map_reduce_levels": int(hub.get("map_reduce_levels") or 0),
					"truncated": bool(hub.get("truncated")),
					"is_fallback": bool(hub.get("_is_fallback")),
					"title_chars": len(str(hub.get("title") or "")),
					"summary_chars": len(str(hub.get("summary") or "")),
					"texture_chars": len(str(hub.get("texture") or "")),
					"texture_parts": len(hub.get("texture_parts") or []),
					"output_chars": int(hub.get("output_chars") or 0),
					"summary_compacted": bool(hub.get("summary_compacted")),
					"summary_over_budget": bool(hub.get("summary_over_budget")),
					"texture_compacted": bool(hub.get("texture_compacted")),
					"texture_over_target": bool(hub.get("texture_over_target")),
					"texture_split": bool(hub.get("texture_split")),
					"texture_split_fallback": bool(hub.get("texture_split_fallback")),
					"compaction_calls": int(hub.get("compaction_calls") or 0),
					"partial_cache_hits": int(hub.get("partial_cache_hits") or 0),
					"partial_cache_total": int(hub.get("partial_cache_total") or 0),
					"model": str(hub.get("model") or ""),
					"large_path": bool(hub.get("large_path")),
					"title": str(hub.get("title") or ""),
					"summary": str(hub.get("summary") or ""),
					"texture": str(hub.get("texture") or ""),
				},
				ensure_ascii=False,
			)
		)
		return

	backup_path: Optional[str] = None
	if not args.no_backup:
		backup_path = backup_hub_payload(memory, collection, session_id, backup_dir=args.backup_dir)
		if not backup_path:
			print(json.dumps({"collection": collection, "session_id": session_id, "backup": None, "result": "no_hub_previo"}, ensure_ascii=False))

	result = resynthesize_session(memory, collection, session_id, force=True)
	print(
		json.dumps(
			{"collection": collection, "session_id": session_id, "backup": backup_path, "result": result},
			ensure_ascii=False,
		)
	)
	if result == "failed":
		# Fail-soft del element_job: registra y sigue con el resto.
		code = int(os.environ.get("RP_SKIP_EXIT_CODE", "0") or 0)
		raise SystemExit(code or 1)


if __name__ == "__main__":
	main()
