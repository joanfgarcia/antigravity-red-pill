#!/usr/bin/env python3
"""memento_replay_recall.py — replay del query log de recall (RFC-002 §4.6, Fase 4 §6.10).

Re-ejecuta las queries reales de `search_memory_research` (persistidas en
`search_query_log.jsonl`) contra el corpus curado (work/social_memories) y mide
el recall: hit rate, top_score medio y cuántos hits proceden de engramas
ascendidos desde Memento (`origin: memento`).

Es la evidencia del umbral Q4 antes de flipear el gate estático: si los engramas
que ASCENDERÍAN responden bien a las queries reales (top_score alto, contribución
significativa), el gate no pierde recall. La Fase 4 NO flipea a ciegas — espera
este replay o el refuerzo acumulado, lo que llegue primero con evidencia.

Uso:
    uv run python scripts/memento_replay_recall.py
    uv run python scripts/memento_replay_recall.py --limit 50
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load_queries(log_path: Path) -> List[Dict[str, Any]]:
	"""Lee el query log JSONL → [{ts, action, query}]. Best-effort por línea."""
	queries = []
	if not log_path.exists():
		return queries
	for line in log_path.read_text(encoding="utf-8").splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			entry = json.loads(line)
			if entry.get("query"):
				queries.append(entry)
		except Exception:
			continue
	return queries


def replay_recall(memory_manager: Any = None, log_path: Path | None = None, limit: int | None = None) -> Dict[str, Any]:
	"""Ejecuta las queries del log contra work/social_memories (recall real con
	refuerzo) y mide la contribución de los engramas ascendidos (origin=memento)."""
	if memory_manager is None:
		from red_pill.memory import MemoryManager

		memory_manager = MemoryManager()
	if log_path is None:
		from red_pill.core.paths import get_data_dir

		log_path = get_data_dir() / "search_query_log.jsonl"

	queries = load_queries(Path(log_path))
	if limit:
		queries = queries[-limit:]

	stats: Dict[str, Any] = {
		"queries": len(queries),
		"con_hits": 0,
		"hits_total": 0,
		"top_score_acumulado": 0.0,
		"hits_memento": 0,
		"top_memento": 0,
	}

	for entry in queries:
		query = entry["query"]
		hits_any = False
		for collection in ("work_memories", "social_memories"):
			if not memory_manager.client.collection_exists(collection):
				continue
			results = memory_manager.search_and_reinforce(collection, query, limit=3, caller="memento_replay")
			if not results:
				continue
			hits_any = True
			top_score = float(getattr(results[0], "score", 0.0) or 0.0)
			stats["top_score_acumulado"] += top_score
			for r in results:
				stats["hits_total"] += 1
				if (r.payload or {}).get("origin") == "memento":
					stats["hits_memento"] += 1
		if hits_any:
			stats["con_hits"] += 1

	if stats["queries"]:
		stats["top_score_medio"] = round(stats["top_score_acumulado"] / stats["queries"], 3)
	stats["hit_rate"] = round(100 * stats["con_hits"] / max(stats["queries"], 1), 1)
	stats["pct_hits_memento"] = round(100 * stats["hits_memento"] / max(stats["hits_total"], 1), 1)
	return stats


def main() -> None:
	parser = argparse.ArgumentParser(description="Replay del query log de recall (umbral Q4).")
	parser.add_argument("--limit", type=int, default=None, help="Solo las últimas N queries")
	args = parser.parse_args()

	stats = replay_recall(limit=args.limit)
	print(f"[REPLAY] queries: {stats['queries']} | hit rate: {stats['hit_rate']}% ({stats['con_hits']})")
	print(f"[REPLAY] top_score medio: {stats.get('top_score_medio', 0)} | hits totales: {stats['hits_total']}")
	print(f"[REPLAY] hits de engramas ascendidos (origin=memento): {stats['hits_memento']} ({stats['pct_hits_memento']}%)")
	if stats["queries"] == 0:
		print("[REPLAY] corpus de queries vacío — aún no hay evidencia Q4 para flipear el gate.")
	elif stats["hits_memento"] == 0:
		print("[REPLAY] aún no hay engramas ascendidos en Qdrant (gate en sombra) — no hay evidencia de su recall.")
	else:
		print("[REPLAY] evidencia parcial: los ascendidos contribuyen al recall. Revisar antes de flipear el gate.")


if __name__ == "__main__":
	main()
