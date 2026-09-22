#!/usr/bin/env python3
"""memento_recalibrate.py — cata y recalibración de la curaduría Memento.

Herramienta recurrente: cada vez que se cambian los modelos de las fases Memento
(distill/refine) hay que re-medir. Acciones:

  stats                        distribución de significance (ascendidos / no) por categoría
  bands --work TH --social TH  escenarios de umbral: qué entra / sale / queda al límite
  audit-category -n N          el LLM re-etiqueta la categoría → matriz de confusión vs
                               `category_score` (calibración del CLASIFICADOR)
  audit-significance -n N      el LLM juzga trivial/importante en una banda de significance
      --lo 0.55 --hi 0.65        → % trivial por banda (guía para fijar el UMBRAL)
  report --work TH --social TH reporte markdown (stats + bands + muestras) para el desk

Determinista: stats/bands/report (sin LLM). Los audit-* usan el LLM local vía
`http_transport` (task=distill) y `--engine` fija RP_LLM_MODEL para comparar modelos.
`--dry-run` imprime la muestra sin llamar al LLM (cata manual).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SYSTEM_CLASSIFY = (
	"Eres el curador de memoria del operador. Clasificas refinados de conversaciones en: "
	"work (técnico/proyecto/decisiones de ingeniería), social (vínculo, emociones, vida personal "
	"del operador) o personal-history (biografía, relaciones íntimas, familia). "
	"Responde SOLO un JSON array: [{\"i\": <índice>, \"category\": \"work|social|personal-history\"}]."
)
SYSTEM_JUDGE = (
	"Eres el curador de memoria del operador. Para cada fragmento decide si es memoria valiosa y "
	"durable para el operador (important) o contenido operativo/trivial/duplicado (trivial). "
	"Responde SOLO un JSON array: [{\"i\": <índice>, \"verdict\": \"important|trivial\", \"reason\": \"<8 palabras>\"}]."
)


def _memento_root() -> Path:
	from red_pill.memento import get_memento_root

	return get_memento_root()


def _parse_frontmatter(txt: str) -> Dict[str, Any]:
	m = re.match(r"^---\n(.*?)\n---\n(.*)", txt, re.S)
	fm: Dict[str, Any] = {}
	if m:
		for line in m.group(1).splitlines():
			if ":" in line:
				key, _, value = line.partition(":")
				fm[key.strip()] = value.strip().strip("'\"")
	return fm


def load_rows(root: Path) -> List[Dict[str, Any]]:
	"""Refines del árbol → filas normalizadas (significance, categoría, sello, snippet)."""
	rows: List[Dict[str, Any]] = []
	for path in sorted(root.rglob("refine/*.md")):
		try:
			txt = path.read_text(encoding="utf-8", errors="replace")
		except OSError:
			continue
		fm = _parse_frontmatter(txt)
		body = re.sub(r"\s+", " ", (re.match(r"^---\n.*?\n---\n(.*)", txt, re.S) or [None, txt])[1]).strip()
		try:
			sig = float(fm.get("significance", 0) or 0)
		except (TypeError, ValueError):
			sig = 0.0
		try:
			cat_score = float(fm.get("category_score", 0.5) or 0.5)
		except (TypeError, ValueError):
			cat_score = 0.5
		rows.append(
			{
				"path": path,
				"sig": sig,
				"cat_score": cat_score,
				"cat": "work" if cat_score >= 0.5 else "social",
				"asc": fm.get("ascended") == "true",
				"snippet": body[:400],
			}
		)
	return rows


def _pct(values: List[float], q: float) -> Optional[float]:
	if not values:
		return None
	v = sorted(values)
	return round(v[int((len(v) - 1) * q)], 3)


def stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
	out: Dict[str, Any] = {}
	for cat in ("work", "social"):
		a = [r["sig"] for r in rows if r["cat"] == cat and r["asc"]]
		n = [r["sig"] for r in rows if r["cat"] == cat and not r["asc"]]
		out[cat] = {
			"ascendidos": len(a),
			"no_ascendidos": len(n),
			"asc_min": min(a) if a else None,
			"asc_p25": _pct(a, 0.25),
			"asc_median": _pct(a, 0.5),
			"no_asc_median": _pct(n, 0.5),
			"no_asc_p90": _pct(n, 0.9),
			"no_asc_max": max(n) if n else None,
		}
	return out


def bands(rows: List[Dict[str, Any]], th_work: float, th_social: float) -> Dict[str, Any]:
	"""Escenario de umbrales: `entran` (no asc ≥ TH), `salen` (asc < TH), `limite` (TH-0.05..TH)."""
	th = {"work": th_work, "social": th_social}
	out: Dict[str, Any] = {}
	for cat in ("work", "social"):
		out[cat] = {
			"entran": sorted([r for r in rows if r["cat"] == cat and not r["asc"] and r["sig"] >= th[cat]], key=lambda r: -r["sig"]),
			"salen": sorted([r for r in rows if r["cat"] == cat and r["asc"] and r["sig"] < th[cat]], key=lambda r: r["sig"]),
			"limite": sorted(
				[r for r in rows if r["cat"] == cat and not r["asc"] and th[cat] - 0.05 <= r["sig"] < th[cat]], key=lambda r: -r["sig"]
			),
		}
	return out


def _sample(items: List[Dict[str, Any]], n: int, seed: int) -> List[Dict[str, Any]]:
	return random.Random(seed).sample(items, min(n, len(items)))


def _llm_json(system: str, user: str) -> List[Dict[str, Any]]:
	from red_pill.memento.agentic import http_transport, llm_available

	if not llm_available():
		raise SystemExit("[recalibrate] LLM local no disponible — audit cancelado.")
	raw = http_transport(system, user, max_tokens=2048)
	m = re.search(r"\[.*\]", raw, re.S)
	if not m:
		raise SystemExit(f"[recalibrate] respuesta no parseable: {raw[:200]}")
	try:
		data = json.loads(m.group(0))
	except json.JSONDecodeError as e:
		raise SystemExit(f"[recalibrate] JSON inválido: {e}")
	return data if isinstance(data, list) else []


def _listing(items: List[Dict[str, Any]], chars: int = 500) -> str:
	return "\n\n".join(f"[{i}] {it['snippet'][:chars]}" for i, it in enumerate(items))


def audit_category(items: List[Dict[str, Any]], seed: int, dry_run: bool) -> Dict[str, Any]:
	"""El LLM re-etiqueta y se compara con `category_score` → confusión + desacuerdos."""
	if dry_run:
		for i, it in enumerate(items):
			print(f"[{i}] (score={it['cat_score']:.2f} → {it['cat']}) {it['snippet'][:160]}")
		return {}
	data = _llm_json(SYSTEM_CLASSIFY, f"Clasifica estos {len(items)} fragmentos:\n\n{_listing(items)}")
	confusion: Dict[str, Dict[str, int]] = {}
	disagree: List[Dict[str, Any]] = []
	for row in data:
		try:
			idx = int(row.get("i"))
		except (TypeError, ValueError):
			continue
		if not (0 <= idx < len(items)):
			continue
		llm_cat = str(row.get("category", "?"))
		it = items[idx]
		confusion.setdefault(it["cat"], {}).setdefault(llm_cat, 0)
		confusion[it["cat"]][llm_cat] += 1
		if llm_cat != it["cat"]:
			disagree.append({"score_cat": it["cat"], "cat_score": it["cat_score"], "llm_cat": llm_cat, "snippet": it["snippet"][:200]})
	n = sum(sum(v.values()) for v in confusion.values()) or 1
	ok = sum(v.get(k, 0) for k, v in confusion.items())
	return {"n": n, "acuerdo": round(ok / n, 3), "confusion": confusion, "desacuerdos": disagree}


def audit_significance(items: List[Dict[str, Any]], seed: int, dry_run: bool) -> Dict[str, Any]:
	"""El LLM juzga trivial/importante en la banda → % trivial (guía del umbral)."""
	if dry_run:
		for i, it in enumerate(items):
			print(f"[{i}] ({it['sig']:.2f}) {it['snippet'][:160]}")
		return {}
	data = _llm_json(SYSTEM_JUDGE, f"Juzga estos {len(items)} fragmentos:\n\n{_listing(items)}")
	verdicts = {"important": 0, "trivial": 0}
	triviales: List[Dict[str, Any]] = []
	for row in data:
		v = str(row.get("verdict", "")).lower()
		if v not in verdicts:
			continue
		verdicts[v] += 1
		try:
			idx = int(row.get("i"))
		except (TypeError, ValueError):
			idx = -1
		if v == "trivial" and 0 <= idx < len(items):
			triviales.append({"sig": items[idx]["sig"], "reason": row.get("reason", ""), "snippet": items[idx]["snippet"][:200]})
	total = verdicts["important"] + verdicts["trivial"] or 1
	return {"n": total, "pct_trivial": round(verdicts["trivial"] / total, 3), "triviales": triviales}


def _print_stats(rows: List[Dict[str, Any]]) -> None:
	st = stats(rows)
	print("categoría | ascendidos | no_asc | asc[min/p25/med] | no_asc[med/p90/max]")
	for cat, s in st.items():
		print(
			f"{cat:9} | {s['ascendidos']:10} | {s['no_ascendidos']:6} | {s['asc_min']}/{s['asc_p25']}/{s['asc_median']} | "
			f"{s['no_asc_median']}/{s['no_asc_p90']}/{s['no_asc_max']}"
		)


def _print_bands(bd: Dict[str, Any], samples: int) -> None:
	for cat, b in bd.items():
		print(f"\n=== {cat}: entran={len(b['entran'])} salen={len(b['salen'])} limite={len(b['limite'])} ===")
		for label, key in (("ENTRAN", "entran"), ("SALEN", "salen"), ("LÍMITE", "limite")):
			for r in b[key][:samples]:
				print(f"  [{label}] {r['sig']:.2f} {r['snippet'][:150]}")


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("action", choices=["stats", "bands", "audit-category", "audit-significance", "report"])
	parser.add_argument("--root", type=Path, default=None, help="Raíz Memento (default: la configurada).")
	parser.add_argument("--work", type=float, default=0.70, help="Umbral work propuesto (bands/report).")
	parser.add_argument("--social", type=float, default=0.65, help="Umbral social propuesto (bands/report).")
	parser.add_argument("--lo", type=float, default=0.55, help="Banda significance: límite inferior.")
	parser.add_argument("--hi", type=float, default=0.65, help="Banda significance: límite superior.")
	parser.add_argument("-n", type=int, default=30, help="Muestras para los audit-*.")
	parser.add_argument("--samples", type=int, default=8, help="Muestras impresas por banda.")
	parser.add_argument("--seed", type=int, default=7, help="Semilla del muestreo.")
	parser.add_argument("--engine", default="", help="Modelo para el LLM (RP_LLM_MODEL).")
	parser.add_argument("--dry-run", action="store_true", help="Solo imprime la muestra (sin LLM).")
	args = parser.parse_args()

	if args.engine:
		os.environ["RP_LLM_MODEL"] = args.engine
		os.environ.setdefault("RP_LLM_TASK", "distill")

	rows = load_rows(args.root or _memento_root())
	if args.action == "stats":
		_print_stats(rows)
		return
	if args.action == "bands":
		_print_bands(bands(rows, args.work, args.social), args.samples)
		return
	if args.action == "report":
		_print_stats(rows)
		_print_bands(bands(rows, args.work, args.social), args.samples)
		return
	if args.action == "audit-category":
		items = _sample(rows, args.n, args.seed)
		res = audit_category(items, args.seed, args.dry_run)
		if res:
			print(f"acuerdo={res['acuerdo']} (n={res['n']}) confusión={res['confusion']}")
			for d in res["desacuerdos"][:10]:
				print(f"  [score→{d['score_cat']} vs LLM→{d['llm_cat']}] {d['snippet'][:140]}")
		return
	items = [r for r in rows if args.lo <= r["sig"] < args.hi]
	res = audit_significance(_sample(items, args.n, args.seed), args.seed, args.dry_run)
	if res:
		print(f"banda [{args.lo},{args.hi}): n={res['n']} trivial={res['pct_trivial']}")
		for t in res["triviales"][:10]:
			print(f"  [{t['sig']:.2f}] {t['reason']} :: {t['snippet'][:120]}")


if __name__ == "__main__":
	main()
