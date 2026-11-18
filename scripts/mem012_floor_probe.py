#!/usr/bin/env python3
"""MEM-012 · F0 — calibración del suelo de abstención sobre el Búnker real.

La pregunta de F0 es una sola: **¿qué similitud separa «me consta» de «no me
consta»?** El plan (D-AB-02) arranca con `SW_RECALL_ABSTENTION_FLOOR=0.30` y pide
cerrarlo con una muestra amplia (~30 casos con negativos duros). Este instrumento
produce esa muestra y la tabla de separación; no implementa la abstención (eso es
F1/F2) y no escribe nada.

Tres decisiones que el instrumento toma y que conviene leer antes de mirar cifras:

- **Se mide `max(similarity)` de los hits devueltos**, no `hits[0].score`: con
  hybrid + MMR + boost el top-1 fusionado no es el de mayor similitud (auditoría
  MEM-011 F-5). La diferencia entre `top1` y `max_sim` se reporta.
- **Camino real**: `_search_and_reinforce_impl` con `hybrid=True`, las mismas flags
  de producción. La escritura de refuerzo se neutraliza (`_reinforce_points`), así
  que la pasada es read-only de verdad.
- **Casos muertos**: si las agujas de un positivo no existen en su colección, el
  caso se marca `dead` y queda fuera de la calibración. Es el defecto que tenía
  `directiva-770` (pedía «770» y «pacto» y hoy no hay ningún punto con ambos).

La salida no decide: mide. El suelo se elige con la tabla de separación y con las
dos posturas de D-AB-04 (inyección estricta, inspección con banda marcada).

Uso:
	.venv/bin/python scripts/mem012_floor_probe.py --json /tmp/mem012-floor.json
	.venv/bin/python scripts/mem012_floor_probe.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

CASES_DEFAULT = Path(__file__).with_name("mem012_floor_cases.json")
NEEDED = ("name", "query", "collection", "kind")
FLOOR_SCAN = [round(0.20 + 0.01 * i, 2) for i in range(31)]  # 0.20 .. 0.50


def _norm(text: Any) -> str:
	return str(text or "").lower()


def load_cases(path: Path) -> List[Dict[str, Any]]:
	data = json.loads(path.read_text(encoding="utf-8"))
	cases = data["cases"] if isinstance(data, dict) else data
	for case in cases:
		missing = [k for k in NEEDED if k not in case]
		if missing:
			raise SystemExit(f"[floor] caso {case.get('name', '?')} sin campos: {missing}")
		case.setdefault("expect", [])
	return cases


def corpus_text(manager: Any, collection: str, cache: Dict[str, str]) -> str:
	"""Todo el `content` de una colección, en minúsculas (detector de casos muertos)."""
	if collection in cache:
		return cache[collection]
	parts: List[str] = []
	offset = None
	while True:
		batch, offset = manager.client.scroll(
			collection_name=collection,
			limit=512,
			offset=offset,
			with_payload=["content"],
			with_vectors=False,
		)
		for point in batch:
			parts.append(_norm((point.payload or {}).get("content")))
		if offset is None:
			break
	cache[collection] = "\n".join(parts)
	return cache[collection]


def missing_needles(text: str, expect: Sequence[str]) -> List[str]:
	return [needle for needle in expect if _norm(needle) not in text]


def detail_rank(rows: Sequence[Dict[str, Any]], expect: Sequence[str]) -> Optional[int]:
	needles = [_norm(n) for n in expect if n]
	if not needles:
		return None
	for row in rows:
		if all(n in _norm(row["content"]) for n in needles):
			return int(row["rank"])
	return None


def case_rows(hits: Sequence[Any], limit: int) -> List[Dict[str, Any]]:
	rows: List[Dict[str, Any]] = []
	for rank, hit in enumerate(hits[:limit], start=1):
		payload = getattr(hit, "payload", None) or {}
		content = str(payload.get("content") or "")
		rows.append(
			{
				"rank": rank,
				"id": str(getattr(hit, "id", "")),
				"score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
				"role": payload.get("hub_role") or payload.get("node_type"),
				"content": content,
				"title": (str(payload.get("hub_title") or "") or content.split("\n", 1)[0])[:90],
			}
		)
	return rows


def _distribution(values: Sequence[float]) -> Dict[str, float]:
	if not values:
		return {}
	ordered = sorted(values)

	def pct(p: float) -> float:
		return round(ordered[min(len(ordered) - 1, int(p * (len(ordered) - 1)))], 4)

	return {
		"n": len(ordered),
		"min": round(ordered[0], 4),
		"p25": pct(0.25),
		"p50": pct(0.5),
		"p75": pct(0.75),
		"max": round(ordered[-1], 4),
		"mean": round(st.mean(ordered), 4),
	}


def calibrate(cases: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
	"""Separación positivos/negativos y barrido de suelos candidatos."""
	positives = [c for c in cases if c["kind"] != "negative" and not c["dead"] and c["kind"] != "pending"]
	findable = [c for c in positives if c["detail_rank"] is not None]
	missed = [c for c in positives if c["detail_rank"] is None]
	negatives = [c for c in cases if c["kind"] == "negative"]

	min_pos = min((c["max_sim"] for c in findable), default=None)
	max_neg = max((c["max_sim"] for c in negatives), default=None)
	gap = round(min_pos - max_neg, 4) if min_pos is not None and max_neg is not None else None

	scan: List[Dict[str, Any]] = []
	for floor in FLOOR_SCAN:
		suppressed = sum(1 for c in findable if c["max_sim"] < floor)
		blocked = sum(1 for c in negatives if c["max_sim"] < floor)
		scan.append({"floor": floor, "positives_suppressed": suppressed, "negatives_blocked": blocked})

	full_block = next((row for row in scan if row["negatives_blocked"] == len(negatives)), None)
	best_trade = None
	if full_block is not None:
		at_or_below = [row for row in scan if row["negatives_blocked"] == len(negatives)]
		best_trade = min(at_or_below, key=lambda row: (row["positives_suppressed"], row["floor"]))

	return {
		"positives_total": len(positives),
		"positives_findable": len(findable),
		"positives_missed": [c["name"] for c in missed],
		"positives_max_sim": _distribution([c["max_sim"] for c in findable]),
		"negatives_total": len(negatives),
		"negatives_max_sim": _distribution([c["max_sim"] for c in negatives]),
		"min_positive_max_sim": min_pos,
		"max_negative_max_sim": max_neg,
		"gap": gap,
		"floor_full_block": full_block,
		"floor_best_trade": best_trade,
		"scan": scan,
	}


def run(manager: Any, cases: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
	# Sonda read-only: el camino real puntúa y escribiría refuerzos; se neutraliza.
	manager._reinforce_points = lambda *a, **k: []
	texts: Dict[str, str] = {}
	out: List[Dict[str, Any]] = []
	for case in cases:
		missing = missing_needles(corpus_text(manager, case["collection"], texts), case["expect"])
		hits = manager._search_and_reinforce_impl(
			collection=case["collection"],
			query=case["query"],
			limit=limit,
			hybrid=True,
		)
		rows = case_rows(hits, limit)
		max_sim = max((row["score"] for row in rows), default=None)
		enriched = dict(case)
		enriched.update(
			{
				"rows": rows,
				"top1": rows[0]["score"] if rows else None,
				"max_sim": max_sim,
				"detail_rank": detail_rank(rows, case["expect"]),
				"missing_needles": missing,
				"dead": bool(missing) or (case["kind"] != "negative" and not rows),
			}
		)
		out.append(enriched)
		print(
			f"  {case['name']:<22} {case['kind']:<8} rank={str(enriched['detail_rank']):<5} "
			f"top1={enriched['top1']} max={enriched['max_sim']} "
			f"{'DEAD ' + str(missing) if missing else ''}",
			file=sys.stderr,
		)
	return out


def main(argv: Optional[Sequence[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="MEM-012 F0 — calibración del suelo de abstención")
	parser.add_argument("--cases", type=Path, default=CASES_DEFAULT)
	parser.add_argument("--limit", type=int, default=3)
	parser.add_argument("--json", type=Path, default=None)
	args = parser.parse_args(argv)

	cases = load_cases(args.cases)
	from red_pill.memory import MemoryManager

	manager = MemoryManager()
	print(f"[floor] {len(cases)} casos · limit={args.limit} · camino real (hybrid=True), read-only", file=sys.stderr)
	measured = run(manager, cases, args.limit)
	report = {"cases": measured, "calibration": calibrate(measured), "limit": args.limit}

	cal = report["calibration"]
	print("\n[floor] separación")
	print(f"  positivos localizables: {cal['positives_findable']}/{cal['positives_total']}")
	print(f"  max_sim positivos: {cal['positives_max_sim']}")
	print(f"  max_sim negativos: {cal['negatives_max_sim']}")
	print(f"  min(positivo)={cal['min_positive_max_sim']} · max(negativo)={cal['max_negative_max_sim']} · hueco={cal['gap']}")
	print(f"  suelo que bloquea todos los negativos: {cal['floor_full_block']}")
	print(f"  mejor trueque: {cal['floor_best_trade']}")

	by_collection: Dict[str, Dict[str, Any]] = {}
	for case in measured:
		bucket = by_collection.setdefault(case["collection"], {"positives": [], "negatives": []})
		if case["kind"] == "negative":
			bucket["negatives"].append(case["max_sim"])
		elif case["kind"] != "pending" and not case["dead"] and case["detail_rank"] is not None:
			bucket["positives"].append(case["max_sim"])
	for collection, bucket in by_collection.items():
		pos = bucket["positives"]
		neg = bucket["negatives"]
		bucket["positives_max_sim"] = _distribution(pos)
		bucket["negatives_max_sim"] = _distribution(neg)
		bucket["min_positive"] = min(pos) if pos else None
		bucket["max_negative"] = max(neg) if neg else None
		print(f"  {collection:<20} positivos={len(pos)} (min {bucket['min_positive']}) · negativos={len(neg)} (max {bucket['max_negative']})")
	report["by_collection"] = by_collection

	if args.json:
		args.json.write_text(json.dumps(report, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
		print(f"[floor] volcado: {args.json}", file=sys.stderr)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
