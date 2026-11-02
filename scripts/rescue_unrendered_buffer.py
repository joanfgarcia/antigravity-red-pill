#!/usr/bin/env python3
"""Rescate de turnos del buffer que nunca llegarán a Memento (2026-11-02).

`interaction_memories` es una ventana caliente: a los 30 días se purga. Los turnos
cuya sesión está en Memento se pueden soltar (su copia vive); los que **no tienen
`session_id`** (legacy, o clientes que nunca lo mandaron) no se pueden renderizar
por la vía normal y se pierden en silencio — 6 cayeron la noche del 2026-11-02 y
58 más estaban a menos de 5 días.

Este script los escribe en Memento como sesiones sintéticas `legacy-<día>` y
marca los puntos con ese `session_id`: a partir de ahí, el janitor los trata como
renderizados y puede soltarlos sin pérdida.

Uso:
	scripts/rescue_unrendered_buffer.py --dry-run
	scripts/rescue_unrendered_buffer.py            # escribe en Memento
"""

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SOURCE = "legacy"


def _load_legacy(memory):
	"""Puntos del buffer sin `session_id`: los que no se pueden renderizar."""
	points, _ = memory.client.scroll("interaction_memories", limit=2000, with_payload=True)
	out = []
	for point in points:
		payload = point.payload or {}
		meta = payload.get("metadata") or {}
		if meta.get("session_id"):
			continue
		if not str(payload.get("content") or "").strip():
			continue
		out.append((point, payload, meta))
	return out


def _load_legacy_with_sessions(memory) -> list:
	"""Como `_load_legacy`, pero también los que tienen `session_id` sin renderizar.

	Son turnos de fuentes que ya no los sirven (p. ej. sesiones `pi` que su store
	no descubre). Se rescatan con su id real, marcados como reconstruidos.
	"""
	from red_pill.memento.registry import MementoRegistry

	rendered = {k.split(":", 1)[1] if ":" in k else k for s in MementoRegistry().state["registry"].values() for k in s}
	points, _ = memory.client.scroll("interaction_memories", limit=2000, with_payload=True)
	out = []
	for point in points:
		payload = point.payload or {}
		meta = payload.get("metadata") or {}
		if not str(payload.get("content") or "").strip():
			continue
		sid = str(meta.get("session_id") or "")
		raw = sid.split(":", 1)[1] if ":" in sid else sid
		if raw and raw in rendered:
			continue
		out.append((point, payload, meta, sid))
	return out


def _session_for(ts: float) -> str:
	return f"legacy-{datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')}"


def rescue(*, dry_run: bool = False, include_sessions: bool = False, memory=None, memento_root: Path | None = None, registry_path: Path | None = None) -> dict:
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry
	from red_pill.memento.render import render_session, write_session

	if memory is None:
		from red_pill.memory import MemoryManager

		memory = MemoryManager()
	root = Path(memento_root or get_memento_root())
	registry = MementoRegistry(path=registry_path) if registry_path else MementoRegistry()

	legacy = _load_legacy_with_sessions(memory) if include_sessions else _load_legacy(memory)
	groups: dict[str, list] = defaultdict(list)
	for point, payload, meta, sid in legacy:
		ts = float(payload.get("timestamp") or 0) or time.time()
		groups[sid or _session_for(ts)].append((point, payload, meta, ts))

	report = {"dry_run": dry_run, "points": len(legacy), "sessions": [], "written": 0, "skipped": 0}
	for session_id in sorted(groups):
		items = groups[session_id]
		again = registry.is_rendered(session_id, sources=[SOURCE])
		report["sessions"].append({"session_id": session_id, "points": len(items), "already": again})
		if dry_run:
			continue
		if not again:
			source = SOURCE if session_id.startswith("legacy-") else str(items[0][2].get("originator") or SOURCE).split(":")[0]
			rendered = render_session(
				session_id=session_id,
				source=source,
				originator=source,
				messages=[
					{
						# El blob trae las dos voces (USER/ASSISTANT) y no sabemos quién
						# las dijo: etiquetarlas de Operador fabricaría autoridad.
						"role": "rescatado",
						"content": payload.get("content") or "",
						"timestamp": payload.get("timestamp"),
					}
					for _point, payload, _meta, _ts in items
				],
			)
			write_session(root, rendered)
			registry.upsert(
				source,
				session_id,
				{
					"dir": rendered.dir_rel,
					"month": rendered.month,
					"created_at": rendered.created_at,
					"rendered_at": datetime.now(timezone.utc).isoformat(),
					"message_count": rendered.message_count,
					"body_chars": rendered.body_chars,
					"has_splits": rendered.has_splits,
					"memento_hash": rendered.memento_hash,
					"reconstructed": True,
				},
			)
			registry.save()
			report["written"] += 1
		else:
			report["skipped"] += 1

		# Marca los puntos: el janitor los verá renderizados y podrá soltarlos.
		for point, _payload, meta, _ts in items:
			patched = dict(meta)
			patched["session_id"] = session_id
			patched["rescued_from"] = "interaction_memories"
			memory.client.set_payload(
				collection_name="interaction_memories",
				payload={"metadata": patched},
				points=[point.id],
			)

	return report


def main() -> int:
	parser = argparse.ArgumentParser(description="Rescata a Memento los turnos del buffer sin sesión")
	parser.add_argument("--dry-run", action="store_true", help="solo informa; no escribe")
	parser.add_argument("--include-sessions", action="store_true", help="rescata también los turnos con session_id cuya fuente ya no los sirve")
	args = parser.parse_args()
	report = rescue(dry_run=args.dry_run, include_sessions=args.include_sessions)
	state = " (dry-run)" if report["dry_run"] else ""
	print(
		f"[rescue] puntos legacy={report['points']} · sesiones={len(report['sessions'])}"
		f" · escritas={report['written']} · ya_estaban={report['skipped']}{state}"
	)
	for item in report["sessions"]:
		print(f"  {item['session_id']}  puntos={item['points']}  ya={item['already']}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
