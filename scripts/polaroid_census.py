#!/usr/bin/env python3
"""MEM-011 · F0 — censo del empaquetado por polaroids, en read-only.

Responde, con datos y sin escribir nada: ¿cuántos hubs daría el contrato nuevo
(polaroids enteras fusionadas hasta el presupuesto), cuántos miembros tendría cada
uno, y cuántas polaroids van enteras por exceder el presupuesto solas?

Camino: Memento da las polaroids (una unidad renderizada; el `index.md` entero si
la sesión no se partió) y Qdrant da las hojas (engramas con `session_id` +
`source_lines`, leídos por `scroll`, **sin** reforzar). El mapeo hoja→polaroid es
por rango de líneas; la fusión, `polaroid_pack.pack_polaroids`.

Uso:
	.venv/bin/python scripts/polaroid_census.py [--budget 8000] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from red_pill.memento import get_memento_root
from red_pill.memento.agentic.fragments import work_units
from red_pill.memento.polaroid_pack import (
	needs_parts,
	oversized_polaroids,
	pack_polaroids,
)
from red_pill.metabolism.distiller import hub_budget

_COLLECTIONS = ("work_memories", "social_memories")
_REF_RE = re.compile(r"#l(\d+)-(\d+)")
_SESSION_RE = re.compile(r"^session_id:\s*(.+)$", re.M)


def _session_id(session_dir: Path) -> Optional[str]:
	index = session_dir / "memento" / "index.md"
	try:
		head = index.read_text(encoding="utf-8", errors="ignore")[:1200]
	except OSError:
		return None
	m = _SESSION_RE.search(head)
	return m.group(1).strip().strip('"') if m else None


def _polaroids(session_dir: Path) -> List[Dict[str, Any]]:
	"""Polaroids de una sesión: clave estable (rango de mensajes) y rango de líneas."""
	out: List[Dict[str, Any]] = []
	for unit in work_units(session_dir):
		m = _REF_RE.search(unit.ref or "")
		out.append({"key": unit.key, "lo": int(m.group(1)) if m else None, "hi": int(m.group(2)) if m else None})
	return out


def _index_memento(root: Path) -> Dict[str, Dict[str, Any]]:
	"""session_id -> {dir, polaroids}."""
	index: Dict[str, Dict[str, Any]] = {}
	for index_file in root.rglob("memento/index.md"):
		session_dir = index_file.parent.parent
		sid = _session_id(session_dir)
		if not sid:
			continue
		polaroids = _polaroids(session_dir)
		if not polaroids:
			polaroids = [{"key": "index", "lo": None, "hi": None}]
		index[sid] = {"dir": str(session_dir), "polaroids": polaroids}
	return index


def _engram_stats(manager: Any, collection: str) -> Dict[str, List[tuple]]:
	"""session_id -> [(source_lines, chars)] leídos por scroll (sin reforzar)."""
	per_session: Dict[str, List[tuple]] = defaultdict(list)
	offset = None
	while True:
		points, offset = manager.client.scroll(
			collection_name=collection,
			limit=512,
			offset=offset,
			with_payload=["session_id", "source_lines", "node_type", "content"],
			with_vectors=False,
		)
		for point in points:
			payload = point.payload or {}
			if payload.get("node_type") != "memento_engram":
				continue
			sid = str(payload.get("session_id") or "")
			if not sid:
				continue
			per_session[sid].append((str(payload.get("source_lines") or ""), len(str(payload.get("content") or ""))))
		if offset is None:
			break
	return per_session


def _polaroid_index_of(source_lines: str, polaroids: List[Dict[str, Any]]) -> Optional[int]:
	m = _REF_RE.search(source_lines)
	if not m:
		return 0 if len(polaroids) == 1 else None
	lo, hi = int(m.group(1)), int(m.group(2))
	for idx, pol in enumerate(polaroids):
		if pol["lo"] is None:
			continue
		if not (hi < pol["lo"] or lo > pol["hi"]):
			return idx
	return None


def build_report(budget: int) -> Dict[str, Any]:
	root = get_memento_root()
	index = _index_memento(Path(root))
	from red_pill.memory import MemoryManager

	manager = MemoryManager()
	stats: List[Dict[str, Any]] = []
	unmapped = 0
	unknown_sessions = 0
	seen_sessions: set = set()

	for collection in _COLLECTIONS:
		for sid, leaves in _engram_stats(manager, collection).items():
			meta = index.get(sid)
			if meta is None:
				unknown_sessions += 1
				continue
			seen_sessions.add(sid)
			polaroids = meta["polaroids"]
			chars: List[int] = [0] * len(polaroids)
			members: List[int] = [0] * len(polaroids)
			for source_lines, size in leaves:
				idx = _polaroid_index_of(source_lines, polaroids)
				if idx is None:
					unmapped += 1
					continue
				chars[idx] += size
				members[idx] += 1
			if not any(members):
				continue
			parts = pack_polaroids(chars, budget)
			stats.append(
				{
					"session": sid,
					"collection": collection,
					"polaroids": len(polaroids),
					"parts": len(parts),
					"materialized_parts": len(parts) - 1 if needs_parts(parts) else 0,
					"members": sum(members),
					"oversized": oversized_polaroids(chars, budget),
					"members_per_part": [sum(members[p.start : p.end + 1]) for p in parts],
				}
			)

	def _dist(values: List[int]) -> Dict[str, float]:
		if not values:
			return {}
		values = sorted(values)

		def pct(p: float) -> int:
			return values[min(len(values) - 1, int(p * (len(values) - 1)))]

		return {
			"n": len(values),
			"min": values[0],
			"p50": pct(0.5),
			"p90": pct(0.9),
			"p99": pct(0.99),
			"max": values[-1],
			"mean": round(st.mean(values), 1),
		}

	parts_per_session = [s["parts"] for s in stats]
	members_per_part = [m for s in stats for m in s["members_per_part"]]
	return {
		"budget": budget,
		"sessions": len(stats),
		"sessions_unknown_in_memento": unknown_sessions,
		"leaves_unmapped": unmapped,
		"nodes_total": sum(parts_per_session),
		"parts_total": sum(s["materialized_parts"] for s in stats),
		"sessions_single_part": sum(1 for p in parts_per_session if p == 1),
		"oversized_polaroids": sum(len(s["oversized"]) for s in stats),
		"dist_parts_per_session": _dist(parts_per_session),
		"dist_members_per_part": _dist(members_per_part),
		"worst": sorted(stats, key=lambda s: s["parts"], reverse=True)[:5],
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--budget", type=int, default=0, help="chars por parte (default: hub_budget())")
	ap.add_argument("--json", metavar="PATH")
	args = ap.parse_args()

	budget = args.budget or hub_budget()
	report = build_report(budget)

	print(f"== MEM-011 F0 · censo del empaquetado (budget {budget} chars, read-only) ==")
	for key in (
		"sessions",
		"nodes_total",
		"parts_total",
		"sessions_single_part",
		"oversized_polaroids",
		"leaves_unmapped",
		"sessions_unknown_in_memento",
	):
		print(f"  {key:<28} {report[key]}")
	for label in ("dist_parts_per_session", "dist_members_per_part"):
		d = report[label]
		print(f"  {label}: " + (f"n={d['n']} p50={d['p50']} p90={d['p90']} p99={d['p99']} max={d['max']} media={d['mean']}" if d else "(vacío)"))
	print("  top sesiones por partes:")
	for row in report["worst"]:
		print(
			f"    {row['session'][:40]:<40} polaroids={row['polaroids']:<4} partes={row['parts']:<4} miembros={row['members']:<5} oversized={len(row['oversized'])}"
		)
	if args.json:
		Path(args.json).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
		print(f"informe: {args.json}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
