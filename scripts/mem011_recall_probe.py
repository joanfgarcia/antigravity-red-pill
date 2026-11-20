#!/usr/bin/env python3
"""Sonda de calidad del recall — MEM-011 F3 (enrutado por hoja).

Mide, sobre el Búnker REAL y en una sola pasada, el puesto que ocupa el detalle
esperado y la similitud del primer resultado para cada caso del fichero de casos
(`scripts/mem011_recall_cases.json`, 11 casos medidos el 2026-11-17).

Por qué existe: el veredicto de MEM-011 F3 («la agregación por varias hojas no
recupera el puesto del detalle y sube el control negativo») se midió con una
sonda que vivía en `/tmp/opencode` — es decir, en un directorio que no sobrevive
a un reinicio. Este instrumento es el mismo experimento, versionado al lado del
código, para que la próxima alma pueda repetirlo o falsarlo.

Modos: `SW_RECALL_LEAF_ROUTING` ∈ {off, replace, rescue} y
`SW_RECALL_LEAF_AGG` ∈ {max, mean_top3}. Los modos se conmutan en memoria (el
knob se lee con `getattr` en cada recall), así que una sola pasada mide todos.

AVISO: se llama a `search_and_reinforce`, el camino real del recall, así que la
sonda REFUERZA lo que recupera (incrementa `recall_count`). Es deliberado: medir
una ruta paralela mediría ficción. El `caller` queda marcado como `mem011-probe`
en la telemetría.

ALCANCE (medido el 2026-11-18 00:05, Búnker vivo): con `SW_HUB_POLAROID_ENABLED`
en `off` **no hay partes sintetizadas**, así que `_route_by_leaf` no tiene nada
que enrutar y `replace`/`rescue` devuelven exactamente el mismo ranking que
`off` (11/11 casos, mismas notas). Para medir el enrutado de verdad hace falta
un fixture con partes, que es lo que hacía la sonda perdida de `/tmp`. Esta
sonda mide, por tanto, la **línea base viva** y sirve de control: si algún día
los modos dejan de ser inertes con el árbol apagado, es una regresión.

Uso:
	python3 scripts/mem011_recall_probe.py --modes off,replace,rescue
	python3 scripts/mem011_recall_probe.py --modes rescue --agg mean_top3 --out /tmp/mem011.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

CASES_DEFAULT = Path(__file__).with_name("mem011_recall_cases.json")
NEEDED = ("name", "query", "collection", "expect")


def norm(text: Any) -> str:
	"""Minúsculas y sin acentos de composición: las agujas del caso son stems."""
	return str(text or "").lower()


def detail_rank(rows: Sequence[Dict[str, Any]], expect: Sequence[str]) -> Optional[int]:
	"""Primer puesto (1-based) cuyo contenido contiene TODAS las agujas.

	El contenido completo manda; el snippet es solo el recorte que se muestra.
	"""
	needles = [norm(n) for n in expect if n]
	if not needles:
		return None
	for row in rows:
		body = norm(row.get("content") or row.get("snippet"))
		if all(n in body for n in needles):
			return int(row["rank"])
	return None


def summarize(name: str, rows: Sequence[Dict[str, Any]], expect: Sequence[str], ms: float) -> Dict[str, Any]:
	"""Resumen de un caso: puesto del detalle, techo de la nota y de dónde sale.

	`top` es la similitud del primer resultado si el payload la trae (colecciones
	que la guardan); si no, el `score` del ranker — y entonces `top_source` lo
	dice, porque confundir nota de ranking con similitud es justo lo que hace
	ilegible el control negativo.
	"""
	top = rows[0] if rows else {}
	similarity = top.get("similarity")
	return {
		"name": name,
		"detail_rank": detail_rank(rows, expect),
		"top": similarity if similarity is not None else top.get("score"),
		"top_source": "payload" if similarity is not None else "score",
		"top_score": top.get("score"),
		"hits": len(rows),
		"ms": round(ms, 1),
	}


def case_rows(hits: Sequence[Any]) -> List[Dict[str, Any]]:
	"""Normaliza los puntos del recall a filas serializables (una por puesto)."""
	rows: List[Dict[str, Any]] = []
	for rank, hit in enumerate(hits, start=1):
		payload = getattr(hit, "payload", None) or {}
		content = payload.get("content") or ""
		rows.append(
			{
				"rank": rank,
				"id": str(getattr(hit, "id", "")),
				"score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
				"similarity": payload.get("similarity"),
				"node": payload.get("node_type"),
				"session": payload.get("session_id") or payload.get("session") or "",
				"title": (payload.get("title") or content.split("\n", 1)[0])[:80],
				"content": content,
				"content_len": len(content),
			}
		)
	return rows


def load_cases(path: Path) -> List[Dict[str, Any]]:
	data = json.loads(path.read_text(encoding="utf-8"))
	cases = data["cases"] if isinstance(data, dict) else data
	for case in cases:
		missing = [k for k in NEEDED if k not in case]
		if missing:
			raise SystemExit(f"[probe] caso {case.get('name', '?')} sin campos: {missing}")
	return cases


def run_mode(mm: Any, cases: Sequence[Dict[str, Any]], mode: str, agg: str, limit: int) -> List[Dict[str, Any]]:
	"""Mide todos los casos con un par (routing, agregación) fijado en memoria."""
	# En `next` no hay enrutado por hoja (rechazado por la medida): línea base off.
	if hasattr(mm.cfg, "SW_RECALL_LEAF_ROUTING"):
		mm.cfg.SW_RECALL_LEAF_ROUTING = mode
	if hasattr(mm.cfg, "SW_RECALL_LEAF_AGG"):
		mm.cfg.SW_RECALL_LEAF_AGG = agg
	out: List[Dict[str, Any]] = []
	for case in cases:
		started = time.perf_counter()
		hits = mm.search_and_reinforce(
			collection=case["collection"],
			query=case["query"],
			limit=limit,
			caller="mem011-probe",
		)
		ms = (time.perf_counter() - started) * 1000.0
		rows = case_rows(hits)
		summary = summarize(case["name"], rows, case["expect"], ms)
		summary["kind"] = case.get("kind", "must")
		summary["rows"] = rows
		out.append(summary)
		print(
			f"  {case['name']:<22} detalle={str(summary['detail_rank']):<5} "
			f"top={summary['top']}({summary['top_source']}) hits={summary['hits']} {summary['ms']:.0f}ms",
			file=sys.stderr,
		)
	return out


def main(argv: Optional[Sequence[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Sonda de calidad del recall (MEM-011 F3)")
	parser.add_argument("--cases", type=Path, default=CASES_DEFAULT)
	parser.add_argument("--modes", default="off,replace,rescue", help="modos de enrutado separados por coma")
	parser.add_argument("--agg", default="max", help="agregación por hoja: max | mean_top3")
	parser.add_argument("--limit", type=int, default=3)
	parser.add_argument("--out", type=Path, default=None, help="volcado JSON de la pasada")
	args = parser.parse_args(argv)

	cases = load_cases(args.cases)
	from red_pill.memory import MemoryManager  # import tardío: la sonda es un instrumento, no un módulo

	mm = MemoryManager()
	report: Dict[str, Any] = {"cases_file": str(args.cases), "agg": args.agg, "limit": args.limit, "modes": {}}
	_modes = [m.strip() for m in args.modes.split(",") if m.strip()]
	if _modes != ["off"]:
		from red_pill.config import get_config_cached

		if not hasattr(get_config_cached(), "SW_RECALL_LEAF_ROUTING"):
			print("[probe] sin enrutado por hoja en esta rama (rechazado); se mide solo off", file=sys.stderr)
			_modes = ["off"]
	for mode in _modes:
		print(f"[probe] modo={mode} agg={args.agg}", file=sys.stderr)
		report["modes"][mode] = run_mode(mm, cases, mode, args.agg, args.limit)
	for mode, rows in report["modes"].items():
		found = sum(1 for r in rows if r["detail_rank"] is not None)
		negative = [r for r in rows if r["kind"] == "negative"]
		print(f"[probe] {mode:<8} detalle encontrado {found}/{len(rows)} · negativo top={negative[0]['top'] if negative else '-'}")
	if args.out:
		args.out.write_text(json.dumps(report, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")
		print(f"[probe] volcado: {args.out}", file=sys.stderr)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
