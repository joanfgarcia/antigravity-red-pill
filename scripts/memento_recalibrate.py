#!/usr/bin/env python3
"""memento_recalibrate.py — cata y recalibración de la curaduría Memento.

Herramienta recurrente: cada vez que se cambian los modelos de las fases Memento
(distill/refine) hay que re-medir. Acciones:

	stats                        distribución de significance (ascendidos / no) por categoría
	bands --work TH --social TH  escenarios de umbral: qué entra / sale / queda al límite
	audit-category -n N          el LLM re-etiqueta la categoría → matriz de confusión vs
		`category_score` (calibración del CLASIFICADOR)
	audit-dual -n N              el LLM puntúa DOS ejes (work/social) → acuerdo de enrutado
		--th-work 0.6 --th-social 0.5   dual vs el enrutado legacy (category_score ≥ 0.5)
	audit-stability -n N         flips de ruta bajo 3 protocolos de lote (normal/invertido/
		partido) → mide el anclaje contextual del scorer (compara prompts y modelos)
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
	"work (técnico/operativo: código, tests, comandos, sistemas, configs, arquitectura, infraestructura, "
	"decisiones de ingeniería) o social (vínculo, emociones, vida personal, biografía, relaciones, familia). "
	"Juzga el CONTENIDO, nunca el tono conversacional: un fragmento técnico narrado en primera persona sigue siendo work. "
	"Responde SOLO un JSON array: [{\"i\": <índice>, \"category\": \"work|social\"}]."
)
SYSTEM_JUDGE = (
	"Eres el curador de memoria del operador. Para cada fragmento decide si es memoria valiosa y "
	"durable a largo plazo (important) o contenido trivial (trivial). Durable NO es solo técnico: "
	"decisiones, insights y milestones de ingeniería, Y momentos personales/relacionales/emocionales con "
	"significado (infancia, vínculos, salud, identidad, familia) también son important. "
	"Trivial = small talk, plumbing rutinario, duplicado o relleno. "
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
	"""Refines/anotaciones del árbol → filas normalizadas (significance, categoría, sello, snippet).

	Annotate (MEM-006) trae `dual_route` + ejes; se normaliza `cat_score` al eje
	work para las vistas legacy.
	"""
	rows: List[Dict[str, Any]] = []
	paths = sorted(set(root.rglob("refine/*.md")) | set(root.rglob("annotate/*.md")))
	for path in paths:
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
		route = str(fm.get("dual_route") or "").strip().lower()
		if route in ("work", "social"):
			cat = route
			try:
				cat_score = float(fm.get("work_score", 0.5) or 0.5)
			except (TypeError, ValueError):
				cat_score = 0.5
		else:
			try:
				cat_score = float(fm.get("category_score", 0.5) or 0.5)
			except (TypeError, ValueError):
				cat_score = 0.5
			cat = "work" if cat_score >= 0.5 else "social"
		rows.append(
			{
				"path": path,
				"sig": sig,
				"cat_score": cat_score,
				"cat": cat,
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


def _llm_json(system: str, user: str, temperature: float = 0.1) -> List[Dict[str, Any]]:
	from red_pill.memento.agentic import http_transport, llm_available

	if not llm_available():
		raise SystemExit("[recalibrate] LLM local no disponible — audit cancelado.")
	raw = http_transport(system, user, max_tokens=2048, temperature=temperature)
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


def _judge(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
	"""El LLM re-etiqueta work/social (juez independiente del scorer)."""
	return _llm_json(SYSTEM_CLASSIFY, f"Clasifica estos {len(items)} fragmentos:\n\n{_listing(items)}")


def audit_category(items: List[Dict[str, Any]], seed: int, dry_run: bool) -> Dict[str, Any]:
	"""El LLM re-etiqueta y se compara con `category_score` → confusión + desacuerdos."""
	if dry_run:
		for i, it in enumerate(items):
			print(f"[{i}] (score={it['cat_score']:.2f} → {it['cat']}) {it['snippet'][:160]}")
		return {}
	data = _judge(items)
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


def _dual_route(work: float, social: float, th_work: float, th_social: float) -> Optional[str]:
	"""Ruta por ejes: supera ambos → dominante por MARGEN sobre su umbral (los gates
	son asimétricos, el max crudo sesga); empate exacto de margen → work (en empate,
	work raw = social raw + (th_work − th_social) > social raw, i.e. también el max).
	Uno solo → ese; ninguno → None (ruido, sin ascenso)."""
	over_w = work >= th_work
	over_s = social >= th_social
	if over_w and over_s:
		d_work = work - th_work
		d_social = social - th_social
		if d_work == d_social:
			return "work"
		return "work" if d_work > d_social else "social"
	if over_w:
		return "work"
	if over_s:
		return "social"
	return None


def score_dual(items: List[Dict[str, Any]], dry_run: bool, temperature: float = 0.1) -> List[Dict[str, Any]]:
	"""Puntúa cada refine en DOS ejes (work/social) con el prompt candidato de producción."""
	if dry_run:
		for i, it in enumerate(items):
			print(f"[{i}] {it['snippet'][:160]}")
		return []
	from red_pill.memento.agentic import DUAL_SCORE_SYSTEM, DUAL_SCORE_USER

	data = _llm_json(DUAL_SCORE_SYSTEM, DUAL_SCORE_USER.format(memories=_listing(items)), temperature=temperature)
	out: List[Dict[str, Any]] = []
	for row in data:
		try:
			idx = int(row.get("i"))
			work = max(0.0, min(1.0, float(row.get("work_score", 0.0) or 0.0)))
			social = max(0.0, min(1.0, float(row.get("social_score", 0.0) or 0.0)))
		except (TypeError, ValueError):
			continue
		if 0 <= idx < len(items):
			out.append({"i": idx, "work": work, "social": social})
	return out


def dual_metrics(
	items: List[Dict[str, Any]],
	dual: List[Dict[str, Any]],
	judge: List[Dict[str, Any]],
	th_work: float = 0.6,
	th_social: float = 0.5,
) -> Dict[str, Any]:
	"""Enrutado legacy (`category_score` ≥ 0.5) vs dual (ejes ≥ umbral) contra el juez LLM.

	`sin_ruta`: no llega a ningún umbral (ruido → no asciende). `dual_alto`: supera
	ambos (mixto valioso) → ruta por eje dominante. La comparación es sobre la MISMA
	muestra juzgada: `legacy` cuenta aciertos sobre n; `dual` sobre los enrutados.
	"""
	labels: Dict[int, str] = {}
	for row in judge:
		try:
			idx = int(row.get("i"))
		except (TypeError, ValueError):
			continue
		cat = str(row.get("category", "")).lower().strip()
		if cat in ("work", "social") and 0 <= idx < len(items):
			labels[idx] = cat
	dual_by_i = {d["i"]: d for d in dual}
	legacy_ok = legacy_n = dual_ok = dual_n = sin_ruta = dual_alto = 0
	desacuerdos: List[Dict[str, Any]] = []
	dual_alto_items: List[Dict[str, Any]] = []
	sin_ruta_items: List[Dict[str, Any]] = []
	for idx, it in enumerate(items):
		want = labels.get(idx)
		if want is None:
			continue
		legacy_n += 1
		if it["cat"] == want:
			legacy_ok += 1
		d = dual_by_i.get(idx)
		if d is None:
			continue
		route = _dual_route(d["work"], d["social"], th_work, th_social)
		if route is None:
			sin_ruta += 1
			sin_ruta_items.append({"juez": want, "work": d["work"], "social": d["social"], "snippet": it["snippet"][:200]})
			continue
		if d["work"] >= th_work and d["social"] >= th_social:
			dual_alto += 1
			dual_alto_items.append({"juez": want, "work": d["work"], "social": d["social"], "snippet": it["snippet"][:200]})
		dual_n += 1
		if route == want:
			dual_ok += 1
		else:
			desacuerdos.append(
				{"legacy": it["cat"], "dual": route, "juez": want, "work": d["work"], "social": d["social"], "snippet": it["snippet"][:200]}
			)
	return {
		"n": legacy_n,
		"legacy": round(legacy_ok / legacy_n, 3) if legacy_n else None,
		"dual": round(dual_ok / dual_n, 3) if dual_n else None,
		"n_dual": dual_n,
		"sin_ruta": sin_ruta,
		"dual_alto": dual_alto,
		"desacuerdos": desacuerdos,
		"dual_alto_items": dual_alto_items,
		"sin_ruta_items": sin_ruta_items,
	}


def audit_stability(items: List[Dict[str, Any]], th_work: float = 0.6, th_social: float = 0.5, temperature: float = 0.1) -> Dict[str, Any]:
	"""Flips de ruta del scorer bajo 3 protocolos de lote (normal / invertido / partido).

	Mide el anclaje contextual: el mismo item, mismo prompt, distinta composición de
	lote. `union` = items que cambian de ruta en algún protocolo. Es el arnés
	reutilizable para comparar prompts y modelos (`--engine`).
	"""
	n = len(items)
	if n < 6:
		return {"n": n, "n_flips": None, "union": [], "flip_rev": [], "flip_split": [], "scores": {}}

	def route(pair: Any) -> Optional[str]:
		return _dual_route(pair[0], pair[1], th_work, th_social)

	def score(part: List[Dict[str, Any]], remap: Any = None) -> Dict[int, Any]:
		out: Dict[int, Any] = {}
		for d in score_dual(part, False, temperature=temperature):
			k = d["i"] if remap is None else remap(d["i"])
			out[k] = (d["work"], d["social"])
		return out

	base = score(items)
	rev = score(list(reversed(items)), remap=lambda k: n - 1 - k)
	half = n // 2
	split: Dict[int, Any] = {}
	split.update(score(items[:half], remap=lambda k: k))
	split.update(score(items[half:], remap=lambda k: k + half))
	rb, rr, rs = ({i: route(v) for i, v in d.items()} for d in (base, rev, split))
	flip_rev = sorted(i for i in rb if rr.get(i) != rb[i])
	flip_split = sorted(i for i in rb if rs.get(i) != rb[i])
	union = sorted(set(flip_rev) | set(flip_split))
	return {"n": n, "flip_rev": flip_rev, "flip_split": flip_split, "union": union, "n_flips": len(union), "scores": {"base": base, "rev": rev, "split": split}}


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
	parser.add_argument("action", choices=["stats", "bands", "audit-category", "audit-dual", "audit-stability", "audit-significance", "report"])
	parser.add_argument("--root", type=Path, default=None, help="Raíz Memento (default: la configurada).")
	parser.add_argument("--work", type=float, default=0.70, help="Umbral work propuesto (bands/report).")
	parser.add_argument("--social", type=float, default=0.65, help="Umbral social propuesto (bands/report).")
	parser.add_argument("--th-work", type=float, default=0.6, help="Gate dual: umbral del eje work (audit-dual).")
	parser.add_argument("--th-social", type=float, default=0.5, help="Gate dual: umbral del eje social (audit-dual).")
	parser.add_argument("--temp", type=float, default=0.1, help="Temperatura del scorer dual (audit-dual).")
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
	if args.action == "audit-dual":
		items = _sample(rows, args.n, args.seed)
		if args.dry_run:
			score_dual(items, True)
			return
		dual = score_dual(items, False, temperature=args.temp)
		res = dual_metrics(items, dual, _judge(items), args.th_work, args.th_social)
		print(
			f"legacy={res['legacy']} (n={res['n']}) | dual={res['dual']} (n={res['n_dual']}) | "
			f"sin_ruta={res['sin_ruta']} | dual_alto={res['dual_alto']}"
		)
		for d in res["desacuerdos"][:10]:
			print(f"  [legacy→{d['legacy']} dual→{d['dual']} juez→{d['juez']} w={d['work']:.2f} s={d['social']:.2f}] {d['snippet'][:130]}")
		for d in res["dual_alto_items"][:5]:
			print(f"  [MIXTO w={d['work']:.2f} s={d['social']:.2f} juez→{d['juez']}] {d['snippet'][:130]}")
		for d in res["sin_ruta_items"][:5]:
			print(f"  [RUIDO w={d['work']:.2f} s={d['social']:.2f} juez→{d['juez']}] {d['snippet'][:130]}")
		return
	if args.action == "audit-stability":
		items = _sample(rows, args.n, args.seed)
		if args.dry_run:
			for i, it in enumerate(items):
				print(f"[{i}] {it['snippet'][:160]}")
			return
		res = audit_stability(items, args.th_work, args.th_social, args.temp)
		print(f"estabilidad n={res['n']} flips={res['n_flips']} (rev={res['flip_rev']}, split={res['flip_split']})")
		for i in res["union"][:10]:
			b = res["scores"]["base"].get(i)
			r = res["scores"]["rev"].get(i)
			s = res["scores"]["split"].get(i)
			print(f"  [{i}] base={b} rev={r} split={s} :: {items[i]['snippet'][:120]}")
		return
	items = [r for r in rows if args.lo <= r["sig"] < args.hi]
	res = audit_significance(_sample(items, args.n, args.seed), args.seed, args.dry_run)
	if res:
		print(f"banda [{args.lo},{args.hi}): n={res['n']} trivial={res['pct_trivial']}")
		for t in res["triviales"][:10]:
			print(f"  [{t['sig']:.2f}] {t['reason']} :: {t['snippet'][:120]}")


if __name__ == "__main__":
	main()
