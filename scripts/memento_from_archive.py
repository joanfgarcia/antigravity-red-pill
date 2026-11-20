"""Reconstruye un memento desde la colección `archive_memories` de Qdrant.

Cuando no hay verbo nativo (el store de la IDE se purgó, o el alma vivió en otro
arnés), la memoria queda solo en vectores: `archive_memories` guarda el texto de
cada turno, troceado en fragmentos. Esto lo devuelve a la forma que el pipeline
del memento entiende — `memento/index.md` + `raw/raw.json` — para que la crónica
vuelva a existir y el ciclo nocturno pueda trabajar sobre ella.

**Honestidad primero**: lo reconstruido NO es verbatim. Se marca
`reconstructed: true` y `reconstructed_from`, igual que se hizo en 2026-09-10 con
las sesiones antigravity cuyo raw se perdió.

Uso (dentro del sandbox):
	PYTHONPATH=/src/red-pill/src /opt/py/bin/python /src/red-pill/scripts/memento_from_archive.py \
		--out /srv/dokime/xdg/data/red-pill/memento --qdrant http://qdrant:6333 --api-key …
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

FIELDS = [
	"content",
	"raw_content",
	"session_id",
	"role",
	"sequence_index",
	"created_at",
	"type",
	"parent_id",
	"chunk_index",
	"total_chunks",
	"_is_fragment",
]


def _post(base: str, path: str, body: Dict[str, Any], key: str) -> Dict[str, Any]:
	req = urllib.request.Request(
		base + path,
		data=json.dumps(body).encode(),
		headers={"content-type": "application/json", "api-key": key},
	)
	with urllib.request.urlopen(req, timeout=120) as r:
		return json.load(r)


def scroll_all(base: str, coll: str, key: str) -> List[Dict[str, Any]]:
	out: List[Dict[str, Any]] = []
	offset = None
	while True:
		body: Dict[str, Any] = {"limit": 256, "with_payload": FIELDS, "with_vector": False}
		if offset:
			body["offset"] = offset
		res = _post(base, f"/collections/{coll}/points/scroll", body, key)["result"]
		for p in res["points"]:
			row = dict(p["payload"])
			row["_id"] = p["id"]
			out.append(row)
		offset = res.get("next_page_offset")
		if not offset:
			return out


def rebuild_session(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
	"""Recompone los mensajes: padres completos y fragmentos unidos por chunk."""
	parents = [p for p in points if not p.get("_is_fragment")]
	orphans = [p for p in points if p.get("_is_fragment")]
	by_parent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
	for f in orphans:
		by_parent[str(f.get("parent_id"))].append(f)

	messages: List[Dict[str, Any]] = []
	for p in parents:
		text = (p.get("raw_content") or p.get("content") or "").strip()
		if text:
			messages.append({"role": p.get("role") or "assistant", "text": text, "ts": p.get("created_at")})

	# Fragmentos cuyo padre no está entre los recuperados: se unen por chunk_index.
	parent_ids = {str(p.get("_id")) for p in parents}
	for pid, chunks in by_parent.items():
		if pid in parent_ids:
			continue
		chunks.sort(key=lambda c: c.get("chunk_index") or 0)
		text = "".join((c.get("content") or "") for c in chunks).strip()
		if text:
			messages.append({"role": chunks[0].get("role") or "assistant", "text": text, "ts": chunks[0].get("created_at")})

	messages.sort(key=lambda m: (m["ts"] or 0, m["role"]))
	return messages


def render_index(session: str, messages: List[Dict[str, Any]], when: str) -> str:
	lines = [
		f"# Memento reconstruido — {session}",
		"",
		f"> Reconstruido el {when} desde `archive_memories` (Qdrant). **No es verbatim**:",
		"> el texto se recompuso desde los fragmentos guardados. Puede faltar contexto,",
		"> y el orden dentro del turno es el del índice de secuencia, no el del reloj.",
		"",
	]
	for m in messages:
		ts = datetime.fromtimestamp(m["ts"] or 0, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
		lines.append(f"## {ts} — {m['role']}")
		lines.append("")
		lines.append(m["text"])
		lines.append("")
	return "\n".join(lines)


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--out", required=True, help="raíz del memento (…/red-pill/memento)")
	ap.add_argument("--qdrant", default="http://localhost:6333")
	ap.add_argument("--api-key", default="")
	ap.add_argument("--collection", default="archive_memories")
	ap.add_argument("--source", default="antigravity_rebuild")
	args = ap.parse_args()

	points = scroll_all(args.qdrant, args.collection, args.api_key)
	by_session: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
	for p in points:
		by_session[str(p.get("session_id") or "sin-sesion")].append(p)

	when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
	root = Path(args.out)
	total_msgs = 0
	print(f"{len(points)} puntos · {len(by_session)} sesiones")

	for session, pts in sorted(by_session.items()):
		messages = rebuild_session(pts)
		if not messages:
			continue
		first_ts = min((m["ts"] or 0) for m in messages)
		month = datetime.fromtimestamp(first_ts, timezone.utc).strftime("%Y-%m")
		base = root / month / args.source / session
		(base / "memento").mkdir(parents=True, exist_ok=True)
		(base / "raw").mkdir(parents=True, exist_ok=True)
		(base / "memento" / "index.md").write_text(render_index(session, messages, when), encoding="utf-8")
		(base / "raw" / "raw.json").write_text(
			json.dumps(
				{
					"cascade_id": session,
					"title": (messages[0]["text"][:80] if messages else session),
					"step_count": len(messages),
					"messages": [{"role": m["role"], "content": m["text"]} for m in messages],
				},
				ensure_ascii=False,
				indent=1,
			),
			encoding="utf-8",
		)
		(base / "raw" / "meta.json").write_text(
			json.dumps(
				{
					"reconstructed": True,
					"reconstructed_from": f"qdrant:{args.collection}",
					"reconstructed_at": when,
					"points": len(pts),
					"messages": len(messages),
				},
				ensure_ascii=False,
				indent=1,
			),
			encoding="utf-8",
		)
		total_msgs += len(messages)
		print(f"  {month}/{session[:8]} · {len(messages):>3} mensajes")
	print(f"total: {total_msgs} mensajes reconstruidos en {root}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
