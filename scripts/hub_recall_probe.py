#!/usr/bin/env python3
"""Probe de calidad de recall de hubs (HUB-RECALL-001, Fase 4).

Mide, para un fixture de consultas etiquetadas, el rank del hub esperado y los
chars que se inyectarían. No escribe en Qdrant (solo búsqueda + refuerzo, que es
un update normal de recall). El fixture vive fuera del repo público.

Uso:
	.venv/bin/python scripts/hub_recall_probe.py --queries state/hub_recall_queries.json
	SW_HUB_KEYWORD_ENABLED=true SW_HUB_BOOST_ENABLED=true \
	.venv/bin/python scripts/hub_recall_probe.py --queries ... --json /tmp/on.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from red_pill.core.paths import get_state_dir  # noqa: E402
from red_pill.memory import MemoryManager  # noqa: E402


def _rank(ids: List[str], expected: str) -> int | None:
	for i, pid in enumerate(ids, 1):
		if pid == expected:
			return i
	return None


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
	n = len(rows)
	hits = {k: sum(1 for row in rows if row.get(f"hit@{k}")) for k in (1, 3, 5)}
	mrr = sum((1.0 / row["rank"]) for row in rows if row.get("rank")) / n if n else 0.0
	top3 = [row["top3_chars"] for row in rows if row.get("top3_chars") is not None]
	expected_chars = [row["expected_chars"] for row in rows if row.get("expected_chars") is not None]
	return {
		"n": n,
		"hit@1": hits[1],
		"hit@3": hits[3],
		"hit@5": hits[5],
		"hit@3_ratio": round(hits[3] / n, 4) if n else 0.0,
		"mrr": round(mrr, 4),
		"avg_top3_chars": round(sum(top3) / len(top3)) if top3 else None,
		"max_top3_chars": max(top3) if top3 else None,
		"max_expected_chars": max(expected_chars) if expected_chars else None,
		"misses": [row["id"] for row in rows if not row.get("hit@3")],
	}


def main() -> None:
	parser = argparse.ArgumentParser(description="Probe de recall de hubs")
	parser.add_argument("--queries", help="Fixture JSON (default: state/hub_recall_queries.json).")
	parser.add_argument("--limit", type=int, default=5, help="Resultados por consulta (default 5).")
	parser.add_argument("--json", help="Escribe el informe completo a esta ruta.")
	args = parser.parse_args()

	path = Path(args.queries) if args.queries else Path(get_state_dir()) / "hub_recall_queries.json"
	queries = json.loads(path.read_text(encoding="utf-8"))
	memory = MemoryManager()
	rows: List[Dict[str, Any]] = []
	for query in queries:
		t0 = time.time()
		results = memory.search_and_reinforce(query["collection"], query["query"], limit=args.limit, caller="hub_recall_probe", hybrid=True)
		elapsed = round((time.time() - t0) * 1000)
		ids = [str(hit.id) for hit in results]
		expected = str(query.get("expected_hub") or "")
		rank = _rank(ids, expected)
		contents = [len(str((hit.payload or {}).get("content") or "")) for hit in results]
		expected_chars = next(
			(len(str((hit.payload or {}).get("content") or "")) for hit in results if str(hit.id) == expected),
			None,
		)
		row: Dict[str, Any] = {
			"id": query["id"],
			"collection": query["collection"],
			"kind": query.get("kind", ""),
			"query": query["query"],
			"expected_hub": expected,
			"rank": rank,
			"hit@1": rank == 1,
			"hit@3": bool(rank and rank <= 3),
			"hit@5": bool(rank and rank <= 5),
			"top3_chars": sum(contents[:3]),
			"expected_chars": expected_chars,
			"elapsed_ms": elapsed,
			"top": ids,
		}
		rows.append(row)

	report = {"queries_file": str(path), "summary": summarize(rows), "rows": rows}
	if args.json:
		Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
	print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
	main()
