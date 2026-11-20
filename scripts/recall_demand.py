#!/usr/bin/env python3
"""MEM-012 · F3 — tasa de abstención y lista de demanda.

Lee los dos artefactos que escribe el recall al presentar:

- `recall_abstention_stats.json` — recalls totales, cuántos se abstuvieron y el
	reparto por colección y por banda de confianza. La tasa sale de aquí.
- `recall_demand.jsonl` — lo que se preguntó y no estaba (solo consultas con
	`no_recall`, con secretos redactados y recortadas). Es la lista de lo que falta
	por recordar.

Uso:
	python3 scripts/recall_demand.py
	python3 scripts/recall_demand.py --limit 50 --json /tmp/demanda.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from red_pill.recall_demand import abstention_rate, load_demand, load_stats


def _pct(value: Optional[float]) -> str:
	return "n/a" if value is None else f"{100.0 * value:.1f} %"


def _fmt_ts(ts: Any) -> str:
	try:
		return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
	except (TypeError, ValueError, OSError):
		return "?"


def main(argv: Optional[list] = None) -> int:
	parser = argparse.ArgumentParser(description="MEM-012 F3 — tasa de abstención y demanda")
	parser.add_argument("--limit", type=int, default=20, help="demandas a mostrar (default 20)")
	parser.add_argument("--json", type=Path, default=None, help="volcado JSON")
	args = parser.parse_args(argv)

	stats = load_stats()
	demand = load_demand(limit=args.limit)
	rate = abstention_rate(stats)

	print("== MEM-012 · abstención ==")
	print(f"  recalls: {stats.get('total', 0)} · no_recall: {stats.get('no_recall', 0)} (tasa {_pct(rate)})")
	print(f"  candidatos por debajo del suelo (acumulado): {stats.get('below_floor_total', 0)}")
	for collection, bucket in sorted((stats.get("by_collection") or {}).items()):
		total = int(bucket.get("total", 0) or 0)
		abstained = int(bucket.get("no_recall", 0) or 0)
		print(f"    {collection:<20} {abstained}/{total}")
	if stats.get("by_confidence"):
		bands = " · ".join(f"{band} {count}" for band, count in sorted(stats["by_confidence"].items()))
		print(f"  por banda: {bands}")

	if demand:
		print("  últimas demandas (lo que se preguntó y no estaba):")
		for entry in demand:
			print(
				f"    {_fmt_ts(entry.get('ts'))} [{entry.get('collection')}] "
				f"{entry.get('confidence')} max={entry.get('max_similarity')} · {entry.get('query')}"
			)
	else:
		print("  sin demandas registradas (o el registro está apagado)")

	if args.json:
		args.json.write_text(
			json.dumps({"stats": stats, "rate": rate, "demand": demand}, ensure_ascii=False, indent="\t") + "\n",
			encoding="utf-8",
		)
		print(f"[demand] volcado: {args.json}", file=sys.stderr)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
