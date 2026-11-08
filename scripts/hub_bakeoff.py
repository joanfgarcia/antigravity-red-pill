#!/usr/bin/env python3
"""Bake-off del carril `hub`: Granite vs Bonsai vs K2 sobre sesiones reales.

QUÉ ES
	Mide la síntesis de hubs del sueño con el MISMO input (miembros reales de
	Qdrant), el MISMO prompt (map-reduce de `synthesize_hub_v2`) y el MISMO
	contrato (`task=hub`), cambiando solo el modelo. No escribe hubs: solo
	sintetiza y registra métricas + muestras para que el Operador decida.

SESIONES
	Tres tamaños reales (8k / 42k / 166k chars) que cubren 2, 6 y 22 particiones
	del map-reduce. La sesión grande es la que más sufre el truncado histórico.

MODELOS
	`granite_8b` (titular actual del hub), `bonsai_2_27b` y `k2_horizon_7b`
	(los que ganaron en Memento). Los dos últimos están declarados como
	candidatos NO-default de `hub` en `task_profiles.yaml` para que el daemon
	los resuelva con `task+model` (K1).

USO
	.venv/bin/python scripts/hub_bakeoff.py --dry-run   # plan
	.venv/bin/python scripts/hub_bakeoff.py --run       # mide (resumible por JSONL)
	.venv/bin/python scripts/hub_bakeoff.py --report    # genera el markdown

	Job: `configs/jobs/hub_bakeoff.yaml` (script_job, BLOCKED tras la
	re-síntesis de hubs). Escribe `docs/BENCHMARKS/HUB_BAKEOFF.{jsonl,md}`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import red_pill.config as cfg  # noqa: E402
from red_pill.core.providers import ProviderRegistry, SipInferenceProvider  # noqa: E402
from red_pill.memory import MemoryManager  # noqa: E402
from red_pill.metabolism.distiller import load_prompt_text, render_hub_items, synthesize_hub_v2  # noqa: E402
from red_pill.metabolism.hub_synthesis import load_session_members, members_to_chunks  # noqa: E402

MODELS = ("granite_8b", "bonsai_2_27b", "k2_horizon_7b")
CONCISE_PROMPT = "hub_synthesis_v2_concise.txt"
SESSIONS = (
	{"label": "small-8k", "collection": "work_memories", "session_id": "01a16785-9a3a-7279-8f01-1d1b2da6c5c5"},
	{"label": "medium-42k", "collection": "work_memories", "session_id": "opencode:ses_e8c768addffe28my8l2TBryWnj"},
	{"label": "large-166k", "collection": "work_memories", "session_id": "opencode:ses_e6522bb5fffe4bTB5MfyeGzU7G"},
)
OUT = ROOT / "docs" / "BENCHMARKS" / "HUB_BAKEOFF.jsonl"
REPORT = ROOT / "docs" / "BENCHMARKS" / "HUB_BAKEOFF.md"

_STOP = {
	"sobre", "entre", "desde", "hasta", "donde", "cuando", "porque", "aunque", "mientras",
	"también", "tambien", "puede", "pueden", "hacer", "hacia", "según", "segun", "después",
	"despues", "antes", "sistema", "sesión", "sesion", "ahora", "tiene", "tienen", "estaba",
	"estaban", "hemos", "hacer", "todos", "todas", "otros", "otras", "desde", "sobre",
	"there", "their", "which", "would", "could", "should", "about", "after", "before",
	"these", "those", "being", "where", "while", "other", "into", "from", "with", "that",
}


def _terms(texts: List[str], top: int = 30) -> List[str]:
	"""Términos salientes por frecuencia documental (una vez por fragmento)."""
	counts: Counter = Counter()
	for text in texts:
		seen = set()
		for word in re.findall(r"[a-záéíóúüñ]{5,}", str(text).lower()):
			if word in _STOP or word in seen:
				continue
			seen.add(word)
			counts[word] += 1
	return [w for w, _ in counts.most_common(top)]


def _coverage(master: str, terms: List[str]) -> float:
	if not terms:
		return 0.0
	low = master.lower()
	return round(sum(1 for t in terms if t in low) / len(terms), 3)


def _alias(model: str) -> str:
	alias = f"hub_bakeoff_{model}"
	try:
		ProviderRegistry.register_inference_provider(alias, SipInferenceProvider(socket_path=cfg.SIP_SOCKET_PATH, model=model))
	except Exception:
		# Si ya estaba registrado, seguimos: el alias apunta a un provider válido.
		pass
	return alias


def _existing() -> set:
	done: set = set()
	if not OUT.exists():
		return done
	for line in OUT.read_text(encoding="utf-8").splitlines():
		try:
			row = json.loads(line)
		except json.JSONDecodeError:
			continue
		done.add((row.get("collection"), row.get("session_id"), row.get("model")))
	return done


def _measure(session: Dict[str, Any], model: str, memory: MemoryManager, concise: bool = False, suffix: str = "") -> Dict[str, Any]:
	members = load_session_members(memory, session["collection"], session["session_id"])
	chunks = members_to_chunks(members)
	input_chars = len(render_hub_items(chunks))
	label_parts = [model]
	if concise:
		label_parts.append("concise")
	if suffix:
		label_parts.append(suffix)
	label_model = "_".join(label_parts)
	override_prompt = load_prompt_text(CONCISE_PROMPT) if concise else None
	t0 = time.time()
	try:
		hub = synthesize_hub_v2(
			chunks,
			override_prompt=override_prompt,
			override_params={"provider_alias": _alias(model)},
		)
		error = ""
	except Exception as e:  # fail-soft: un combo roto no invalida los demás
		hub = {}
		error = f"{type(e).__name__}: {e}"
	latency = round(time.time() - t0, 2)
	summary = str(hub.get("summary") or "")
	partitions = hub.get("partitions") or []
	source_terms = _terms([str(c.get("summary") or "") for c in chunks])
	return {
		"model": label_model,
		"variant": "concise" if concise else "default",
		"label": session["label"],
		"collection": session["collection"],
		"session_id": session["session_id"],
		"members": len(members),
		"input_chars": input_chars,
		"ok": bool(summary) and not hub.get("_is_fallback") and not error,
		"error": error,
		"hierarchical": bool(hub.get("hierarchical")),
		"partition_count": int(hub.get("partition_count") or 0),
		"map_reduce_levels": int(hub.get("map_reduce_levels") or 0),
		"truncated": bool(hub.get("truncated")),
		"summary_chars": len(summary),
		"texture_chars": len(str(hub.get("texture") or "")),
		"title": str(hub.get("title") or ""),
		"lang": str(hub.get("lang") or ""),
		"coverage": _coverage(summary, source_terms),
		"source_terms": source_terms[:12],
		"summary_head": summary[:700],
		"partition_head": str((partitions[0] or {}).get("summary") or "")[:400] if partitions else "",
		"latency_s": latency,
		"compaction_calls": int(hub.get("compaction_calls") or 0),
		"compaction_latency_s": float(hub.get("compaction_latency_s") or 0.0),
		"summary_compacted": bool(hub.get("summary_compacted", False)),
		"summary_over_budget": bool(hub.get("summary_over_budget", False)),
		"texture_over_target": bool(hub.get("texture_over_target", False)),
	}


def _append(row: Dict[str, Any]) -> None:
	OUT.parent.mkdir(parents=True, exist_ok=True)
	with OUT.open("a", encoding="utf-8") as fh:
		fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rows() -> List[Dict[str, Any]]:
	if not OUT.exists():
		return []
	rows = []
	for line in OUT.read_text(encoding="utf-8").splitlines():
		try:
			rows.append(json.loads(line))
		except json.JSONDecodeError:
			continue
	return rows


def _report() -> None:
	rows = _rows()
	if not rows:
		print("sin mediciones todavía")
		return
	models = sorted({r["model"] for r in rows})
	labels = sorted({r["label"] for r in rows})
	lines = [
		"# Hub Bake-off — Granite vs Bonsai vs K2 (2026-11-08)",
		"",
		"Mismo input real, mismo prompt (map-reduce AD-113) y `task=hub`; solo cambia el modelo. Sin escritura de hubs.",
		"",
		"**Ninguna fila trunca** (`truncated=false`). Las variantes `_concise` usan el prompt de 700-900 chars; `_concise_compacted` añade la compaction por reescritura (si no reduce, el summary se conserva y se marca `summary_over_budget`).",
		"",
		"## Agregado por modelo",
		"",
		"| Modelo | n | ok | coverage media | summary chars | particiones | latencia media | compact calls | extra compact |",
		"| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
	]
	for model in models:
		mrows = [r for r in rows if r["model"] == model]
		n = len(mrows)
		ok = sum(1 for r in mrows if r.get("ok"))
		cov = round(sum(float(r.get("coverage") or 0) for r in mrows) / n, 3)
		chars = round(sum(int(r.get("summary_chars") or 0) for r in mrows) / n)
		parts = round(sum(int(r.get("partition_count") or 0) for r in mrows) / n, 1)
		lat = round(sum(float(r.get("latency_s") or 0) for r in mrows) / n, 1)
		ccalls = round(sum(int(r.get("compaction_calls") or 0) for r in mrows) / n, 1)
		cextra = round(sum(float(r.get("compaction_latency_s") or 0) for r in mrows) / n, 1)
		lines.append(f"| {model} | {n} | {ok}/{n} | {cov} | {chars} | {parts} | {lat}s | {ccalls} | {cextra}s |")
	lines += ["", "## Por sesión", "", "| Sesión | Modelo | ok | coverage | summary | particiones | latencia | compact |", "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
	for label in labels:
		for model in models:
			r = next((x for x in rows if x["label"] == label and x["model"] == model), None)
			if not r:
				continue
			lines.append(
				f"| {label} | {model} | {'✅' if r.get('ok') else '❌'} | {r.get('coverage')} | {r.get('summary_chars')} | {r.get('partition_count')} | {r.get('latency_s')}s | {r.get('compaction_calls', 0)} / {r.get('compaction_latency_s', 0.0)}s |"
			)
	lines += ["", "## Muestras (lectura del Operador)", ""]
	for label in labels:
		lines += [f"### {label}", ""]
		for model in models:
			r = next((x for x in rows if x["label"] == label and x["model"] == model), None)
			if not r:
				continue
			lines += [f"**{model}** — {r.get('title') or '(sin título)'}", "", f"> {str(r.get('summary_head') or r.get('error') or '').rstrip()}", ""]
			if r.get("partition_head"):
				lines += [f"_partición 1_: {str(r['partition_head']).rstrip()}", ""]
	REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
	print(f"report: {REPORT}")


def main() -> None:
	parser = argparse.ArgumentParser(description="Bake-off del carril hub")
	parser.add_argument("--run", action="store_true", help="Mide todos los combos pendientes (manual).")
	parser.add_argument("--run-element", action="store_true", help="Mide el combo de RP_ELEMENT (job).")
	parser.add_argument("--list", action="store_true", help="Imprime los combos como JSON (elements_command).")
	parser.add_argument("--report", action="store_true", help="Genera el markdown desde el JSONL.")
	parser.add_argument("--dry-run", action="store_true", help="Imprime el plan sin LLM.")
	parser.add_argument("--concise", action="store_true", help="Usa el prompt CONCISE (700-900 chars) en el maestro.")
	parser.add_argument("--suffix", default="", help="Sufijo de la variante en el label (p. ej. compacted).")
	parser.add_argument("--models", default=",".join(MODELS), help="Modelos separados por coma.")
	parser.add_argument("--sessions", default=",".join(s["label"] for s in SESSIONS), help="Labels separados por coma.")
	args = parser.parse_args()

	models = [m.strip() for m in args.models.split(",") if m.strip()]
	sessions = [s for s in SESSIONS if s["label"] in {x.strip() for x in args.sessions.split(",")}]
	elements = [{**s, "model": m} for s in sessions for m in models]

	if args.list:
		print(json.dumps(elements, ensure_ascii=False))
		return
	if args.report:
		_report()
		return
	if args.dry_run or not (args.run or args.run_element):
		for e in elements:
			print(f"{e['label']:>12} | {e['model']:>15} | {'concise' if args.concise else 'default'} | {e['collection']} | {e['session_id']}")
		return

	memory = MemoryManager()
	if args.run_element:
		raw = os.environ.get("RP_ELEMENT")
		if not raw:
			print("[ERROR] --run-element requiere RP_ELEMENT (job element_job)", file=sys.stderr)
			raise SystemExit(2)
		try:
			element = json.loads(raw)
		except json.JSONDecodeError as e:
			print(f"[ERROR] RP_ELEMENT no es JSON: {e}", file=sys.stderr)
			raise SystemExit(2)
		session = next(
			(s for s in sessions if s["collection"] == element.get("collection") and s["session_id"] == element.get("session_id")),
			None,
		)
		if session is None:
			print(f"[ERROR] elemento fuera de la lista congelada: {element}", file=sys.stderr)
			raise SystemExit(2)
		base_model = str(element.get("model") or "")
		label_parts = [base_model]
		if args.concise:
			label_parts.append("concise")
		if args.suffix:
			label_parts.append(args.suffix)
		label_model = "_".join(label_parts)
		if (session["collection"], session["session_id"], label_model) in _existing():
			print(f"skip {session['label']} / {label_model} (ya medido)")
			return
		row = _measure(session, base_model, memory, concise=args.concise, suffix=args.suffix)
		_append(row)
		_report()
		print(
			f"  → ok={row['ok']} coverage={row['coverage']} parts={row['partition_count']} "
			f"chars={row['summary_chars']} lat={row['latency_s']}s err={row['error'][:120]}",
			flush=True,
		)
		if not row["ok"]:
			code = int(os.environ.get("RP_SKIP_EXIT_CODE", "0") or 0)
			raise SystemExit(code or 1)
		return

	done = _existing()
	for e in elements:
		base_model = e["model"]
		label_parts = [base_model]
		if args.concise:
			label_parts.append("concise")
		if args.suffix:
			label_parts.append(args.suffix)
		label_model = "_".join(label_parts)
		key = (e["collection"], e["session_id"], label_model)
		if key in done:
			print(f"skip {e['label']} / {label_model} (ya medido)")
			continue
		print(f"measure {e['label']} / {label_model} …", flush=True)
		row = _measure(e, base_model, memory, concise=args.concise, suffix=args.suffix)
		_append(row)
		print(
			f"  → ok={row['ok']} coverage={row['coverage']} parts={row['partition_count']} "
			f"chars={row['summary_chars']} lat={row['latency_s']}s err={row['error'][:120]}",
			flush=True,
		)
	_report()


if __name__ == "__main__":
	main()
