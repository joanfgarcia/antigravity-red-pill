#!/usr/bin/env python3
"""RFC-OLV-001 · verificador de la cohorte del olvido (PC-01).

El claim falsable: **ninguna rama con hojas desaparece en una pasada**.

Uso:
.venv/bin/python scripts/olvido_cohort_check.py --write snapshot.json
.venv/bin/python scripts/olvido_cohort_check.py --check snapshot.json

`--write` congela el estado actual (ids por colección, con y sin hojas).
`--check` relee el Búnker y falla (exit 1) si alguna rama que tenía hojas en el
snapshot ya no existe, o si aparecieron marcadores huérfanos nuevos.

El snapshot vive FUERA del repo (desk o memoria de workspace): el proyecto no
referencia el desk, así que la ruta se pasa por argumento.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time

from qdrant_client import QdrantClient

COLLECTIONS = ("work_memories", "social_memories", "story_memories")


def _client() -> QdrantClient:
	url = os.environ.get("QDRANT_URL")
	key = os.environ.get("QDRANT_API_KEY")
	if not url or not key:
		try:
			from red_pill.config import _cfg

			cfg = _cfg()
			url = url or cfg.QDRANT_URL
			key = key or cfg.QDRANT_API_KEY
		except Exception:
			pass
	return QdrantClient(url=url or "http://localhost:6333", api_key=key or None)


def _snapshot(client: QdrantClient) -> dict:
	out: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "collections": {}}
	for collection in COLLECTIONS:
		if not client.collection_exists(collection):
			continue
		points = []
		offset = None
		while True:
			batch, offset = client.scroll(collection_name=collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
			points.extend(batch)
			if offset is None:
				break
		hubs = [p for p in points if (p.payload or {}).get("lazarus_phase") == "synthesis_hub"]
		hub_ids = {str(p.id) for p in hubs}
		members = collections.Counter()
		orphans = 0
		for p in points:
			pl = p.payload or {}
			if not (pl.get("hubbed") and pl.get("hub_id")):
				continue
			members[str(pl["hub_id"])] += 1
			if str(pl["hub_id"]) not in hub_ids:
				orphans += 1
		out["collections"][collection] = {
			"with_leaves": sorted(str(h.id) for h in hubs if members[str(h.id)] > 0),
			"leafless": sorted(str(h.id) for h in hubs if members[str(h.id)] == 0),
			"members_by_hub": {str(h.id): members[str(h.id)] for h in hubs if members[str(h.id)] > 0},
			"orphan_markers": orphans,
		}
	return out


def _check(client: QdrantClient, path: str) -> int:
	with open(path, encoding="utf-8") as fh:
		old = json.load(fh)
	now = _snapshot(client)
	failures: list[str] = []
	for collection, data in (old.get("collections") or {}).items():
		current = now["collections"].get(collection) or {}
		present = set(current.get("with_leaves") or []) | set(current.get("leafless") or [])
		missing = [hid for hid in data.get("with_leaves") or [] if hid not in present]
		if missing:
			failures.append(f"{collection}: {len(missing)} ramas CON hojas desaparecieron (p.ej. {missing[:3]})")
		before_orphans = int(data.get("orphan_markers") or 0)
		after_orphans = int(current.get("orphan_markers") or 0)
		if after_orphans > before_orphans:
			failures.append(f"{collection}: marcadores huérfanos {before_orphans} -> {after_orphans}")
		print(
			f"{collection}: ramas con hojas {len(data.get('with_leaves') or [])} -> {len(current.get('with_leaves') or [])} · "
			f"huérfanos {before_orphans} -> {after_orphans}"
		)
	if failures:
		print("\nPC-01 FALLA:")
		for f in failures:
			print(f"  - {f}")
		return 1
	print("\nPC-01 OK: ninguna rama con hojas desapareció y no hay huérfanos nuevos.")
	return 0


def main() -> int:
	ap = argparse.ArgumentParser(description="Cohorte del olvido: snapshot y comprobación (RFC-OLV-001 PC-01)")
	group = ap.add_mutually_exclusive_group(required=True)
	group.add_argument("--write", metavar="PATH", help="Congelar el estado actual en PATH")
	group.add_argument("--check", metavar="PATH", help="Comprobar el Búnker contra el snapshot en PATH")
	args = ap.parse_args()
	client = _client()
	if args.write:
		data = _snapshot(client)
		with open(args.write, "w", encoding="utf-8") as fh:
			json.dump(data, fh, indent=1)
		print(f"snapshot escrito: {args.write}")
		for name, col in data["collections"].items():
			print(f"  {name}: {len(col['with_leaves'])} con hojas · {len(col['leafless'])} sin hojas · huérfanos {col['orphan_markers']}")
		return 0
	return _check(client, args.check)


if __name__ == "__main__":
	sys.exit(main())
