#!/usr/bin/env python3
"""Genera el fixture de consultas de recall para hubs (HUB-RECALL-001, Fase 4).

El set vive FUERA del repo público (state del Búnker): las consultas pueden
contener memoria privada. Este script solo escribe el JSON, no ejecuta recall.

Uso:
    .venv/bin/python scripts/hub_recall_fixture.py
    .venv/bin/python scripts/hub_recall_fixture.py --out /ruta/queries.json --per-collection 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from red_pill.core.paths import get_state_dir  # noqa: E402
from red_pill.memory import MemoryManager  # noqa: E402
from red_pill.metabolism.hub_synthesis import find_stale_hubs  # noqa: E402


def _quantile_pick(rows: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
	if not rows:
		return []
	if len(rows) <= n:
		return list(rows)
	picked: List[Dict[str, Any]] = []
	for i in range(n):
		idx = round(i * (len(rows) - 1) / max(1, n - 1))
		row = rows[idx]
		if row not in picked:
			picked.append(row)
	return picked


def main() -> None:
	parser = argparse.ArgumentParser(description="Fixture de consultas de recall para hubs")
	parser.add_argument("--out", help="Ruta del JSON (default: state/hub_recall_queries.json).")
	parser.add_argument("--per-collection", type=int, default=10, help="Hubs por colección (default 10).")
	parser.add_argument("--limit", type=int, default=20, help="Máximo total de consultas (default 20).")
	args = parser.parse_args()

	memory = MemoryManager()
	blocked_ids = {(row["collection"], row["hub_id"]) for row in find_stale_hubs(memory) if row.get("hub_migration_blocked")}
	queries: List[Dict[str, Any]] = []
	seen: set = set()
	for collection in ("work_memories", "social_memories"):
		hubs: List[Dict[str, Any]] = []
		offset = None
		while True:
			batch, offset = memory.client.scroll(collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
			for point in batch:
				payload = point.payload or {}
				if (payload.get("node_type") or payload.get("lazarus_phase")) != "synthesis_hub":
					continue
				if int(payload.get("hub_synth_version") or 0) < 3:
					continue
				if (collection, str(point.id)) in blocked_ids:
					continue
				title = str(payload.get("hub_title") or "").strip()
				terms = [str(t) for t in (payload.get("hub_terms") or []) if str(t).strip()]
				if not title and not terms:
					continue
				hubs.append(
					{
						"collection": collection,
						"hub_id": str(point.id),
						"session_id": payload.get("session_id"),
						"title": title,
						"terms": terms,
						"content_chars": len(str(payload.get("content") or "")),
					}
				)
			if offset is None:
				break
		hubs.sort(key=lambda row: row["content_chars"])
		for hub in _quantile_pick(hubs, args.per_collection):
			title = hub["title"]
			if len(title) >= 15:
				key = (hub["collection"], title.lower())
				if key not in seen:
					seen.add(key)
					queries.append(
						{
							"id": f"{hub['collection'][:5]}-{hub['hub_id'][:8]}-title",
							"collection": hub["collection"],
							"query": title,
							"expected_hub": hub["hub_id"],
							"expected_session": hub["session_id"],
							"kind": "title",
						}
					)
			# Ancla distintiva que no esté ya en el título (prueba la pata keyword).
			anchor = next((term for term in hub["terms"] if len(term) >= 5 and term.lower() not in title.lower()), "")
			if anchor:
				query = f"{anchor} {title}".strip()
				key = (hub["collection"], query.lower())
				if key not in seen:
					seen.add(key)
					queries.append(
						{
							"id": f"{hub['collection'][:5]}-{hub['hub_id'][:8]}-anchor",
							"collection": hub["collection"],
							"query": query,
							"expected_hub": hub["hub_id"],
							"expected_session": hub["session_id"],
							"kind": "anchor",
						}
					)

	queries = queries[: args.limit]
	out = Path(args.out) if args.out else Path(get_state_dir()) / "hub_recall_queries.json"
	out.parent.mkdir(parents=True, exist_ok=True)
	out.write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
	print(json.dumps({"out": str(out), "queries": len(queries), "kinds": {k: sum(1 for q in queries if q["kind"] == k) for k in ("title", "anchor")}}))


if __name__ == "__main__":
	main()
