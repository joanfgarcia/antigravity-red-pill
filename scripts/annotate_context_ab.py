#!/usr/bin/env python3
"""annotate_context_ab.py — A/B de contexto del carril `annotate` (admisión).

QUÉ ES
	Instrumento del contrato `docs/TECHNICAL/COGNITIVE/MODEL_ADMISSION.md` §2:
	mide si un modelo **produce notas de calidad** al contexto candidato, no solo
	si cabe. Corre el extractor REAL de annotate (mismos prompts v3, mismo
	transporte, mismo presupuesto dinámico) sobre unidades REALES del árbol
	memento, con N repeticiones por unidad y por prompt (work + social).

BRAZOS
	--profile-a   contexto vigente (p. ej. k2_horizon_7b, n_ctx 10.240)
	--profile-b   contexto candidato (p. ej. k2_horizon_7b_ctx16, n_ctx 16.384)
	--chunk-chars N  añade un tercer brazo `C`: las mismas unidades troceadas en
	                 partes de tamaño SIMILAR (ceil(chars/N) trozos), con el perfil
	                 A. Sirve para medir la alternativa de trocear annotate.

UNIDADES
	--unit PATH (repetible) o --auto-quantiles para elegir del árbol real las
	unidades más cercanas a p50/p90/p99 (por chars).

MÉTRICAS (por llamada, a JSONL)
	finish_reason, prompt_tokens/completion_tokens, max_tokens, attempts,
	prompt_cuts (recortes por 500), elapsed_s, error, nº de ideas válidas,
	longitud de las notas, flags de calidad (voz/género/inglés) y el texto crudo.

USO
	PYTHONPATH=src .venv/bin/python scripts/annotate_context_ab.py \\
		--profile-a k2_horizon_7b --profile-b k2_horizon_7b_ctx16 \\
		--auto-quantiles --reps 3 --chunk-chars 8000 \\
		--out /tmp/opencode/annotate_ab

NOTA: no cambia configuración. El perfil B debe existir en model_profiles.yaml
y ser candidato de la task `annotate`. La GPU debe estar libre (el desk se pausa
con `red_pill.core.gpu_desk.pause`, no aquí).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from red_pill.memento.agentic.fragments import balanced_chunks

from red_pill.memento import get_memento_root

DEFAULT_MEMENTO = ""  # se resuelve con get_memento_root() (core/paths.py)
EDGE = "http://127.0.0.1:8760"


# ── unidades ────────────────────────────────────────────────────────────────


def _memento_splits(root: Path) -> List[Path]:
	return [p for p in root.rglob("memento/*.md") if p.name != "index.md"]


def _quantile_pick(root: Path) -> List[Tuple[str, Path]]:
	"""Elige la unidad más cercana a p50/p90/p99 de chars del árbol real."""
	files = sorted(_memento_splits(root), key=lambda p: len(p.read_text(encoding="utf-8")))
	sizes = [len(p.read_text(encoding="utf-8")) for p in files]
	n = len(sizes)
	out = []
	for q in (50, 90, 99):
		target = sizes[min(n - 1, int(n * q / 100))]
		best = min(files, key=lambda p: abs(len(p.read_text(encoding="utf-8")) - target))
		out.append((f"p{q}", best))
	return out


def _get_status() -> Dict[str, Any]:
	with urllib.request.urlopen(f"{EDGE}/status", timeout=5) as r:
		return json.loads(r.read().decode("utf-8"))


def _unload() -> None:
	try:
		req = urllib.request.Request(f"{EDGE}/v1/unload", method="POST")
		urllib.request.urlopen(req, timeout=15).read()
	except Exception as exc:  # el unload es best-effort: si no hay residente, 404
		print(f"[ab] unload: {exc}", file=sys.stderr)


def _wait_loaded(profile: str, n_ctx: int, timeout: float = 300.0) -> None:
	deadline = time.time() + timeout
	while time.time() < deadline:
		st = _get_status()
		if st.get("loaded_profile") == profile and st.get("busy") is False:
			if int(st.get("n_ctx") or 0) >= n_ctx:
				print(f"[ab] cargado {profile} n_ctx={st.get('n_ctx')} modo={st.get('mode')}")
				return
		time.sleep(2)
	raise RuntimeError(f"timeout esperando {profile} a n_ctx {n_ctx}: {_get_status()}")


def _warm(profile: str) -> None:
	"""Una llamada mínima fuerza la carga del perfil en el daemon."""
	body = {
		"messages": [{"role": "user", "content": "Responde solo: ok"}],
		"max_tokens": 8,
		"temperature": 0.0,
		"task": "annotate",
		"model": profile,
		"thinking": "off",
		"device_fallback": ["gpu"],
	}
	req = urllib.request.Request(
		f"{EDGE}/v1/chat/completions",
		data=json.dumps(body).encode("utf-8"),
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	with urllib.request.urlopen(req, timeout=300) as r:
		r.read()


# ── corrida ─────────────────────────────────────────────────────────────────


def _call(runtime, prompts, content: str, prompt_id: str) -> Dict[str, Any]:
	work_scope, social_scope = runtime.annotate_scopes()
	static = {"identity": prompts.IDENTITY_BIO, "work_scope": work_scope, "social_scope": social_scope}
	prompt = prompts.render(prompt_id, static=static, fragment=content)
	budget = runtime.annotate_max_tokens(chars=len(content))
	system = prompts.system(prompt_id) or ""
	t0 = time.monotonic()
	error = None
	raw = ""
	try:
		raw = runtime.http_transport(system, prompt, budget)
		ideas = runtime._extract_json_array(raw) or []
	except Exception as exc:  # noqa: BLE001 — se registra, no se relanza
		error = f"{type(exc).__name__}: {exc}"
		ideas = []
	stats = runtime.last_call_stats()
	return {
		"prompt_id": prompt_id,
		"chars": len(content),
		"max_tokens_requested": budget,
		"error": error,
		"truncated": bool(runtime.last_truncated()),
		"unclosed_json": bool(runtime.unclosed_json_array(raw)) if raw else None,
		"wall_s": round(time.monotonic() - t0, 2),
		"raw_len": len(raw),
		"raw": raw,
		"ideas": ideas,
		"stats": stats,
	}


def _note_metrics(ideas: Sequence[Dict[str, Any]], aq) -> Dict[str, Any]:
	texts = [str(i.get("text") or "").strip() for i in ideas if isinstance(i, dict)]
	texts = [t for t in texts if t]
	flags = {"voice": 0, "gender": 0, "identity": 0}
	english = 0
	first_person = 0
	for t in texts:
		for f in aq.quality_flags(t):
			flags[f] = flags.get(f, 0) + 1
		english += int(aq.looks_english(t))
		first_person += int(aq.is_first_person(t))
	return {
		"notes": len(texts),
		"chars_notes": sum(len(t) for t in texts),
		"median_note_chars": statistics.median([len(t) for t in texts]) if texts else 0,
		"over_600": sum(1 for t in texts if len(t) > 600),
		"first_person": first_person,
		"english": english,
		"flags": flags,
	}


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--profile-a", required=True, help="perfil del contexto vigente")
	ap.add_argument("--profile-b", help="perfil del contexto candidato (si falta, solo A)")
	ap.add_argument("--unit", action="append", default=[], help="ruta de unidad real (repetible)")
	ap.add_argument("--auto-quantiles", action="store_true", help="elegir p50/p90/p99 del árbol memento")
	ap.add_argument("--memento-root", default=DEFAULT_MEMENTO, help="raíz memento (default: get_memento_root())")
	ap.add_argument("--reps", type=int, default=3)
	ap.add_argument("--chunk-chars", type=int, default=0, help="brazo C: trocear a N chars con perfil A")
	ap.add_argument("--out", default="/tmp/opencode/annotate_ab")
	ap.add_argument("--max-units", type=int, default=0)
	args = ap.parse_args()

	memento = Path(os.path.expanduser(args.memento_root)) if args.memento_root else get_memento_root()
	units: List[Tuple[str, Path]] = [("unit", Path(u)) for u in args.unit]
	if args.auto_quantiles:
		units = _quantile_pick(memento)
	if not units:
		ap.error("indica --unit o --auto-quantiles")
	if args.max_units:
		units = units[: args.max_units]

	out = Path(args.out)
	out.mkdir(parents=True, exist_ok=True)
	calls_dir = out / "calls"
	calls_dir.mkdir(exist_ok=True)

	os.environ["RP_LLM_TASK"] = "annotate"
	os.environ["RP_LLM_THINKING"] = "off"
	os.environ["RP_LLM_DEVICE_FALLBACK"] = '["gpu"]'

	from red_pill.core import model_runtime as mr
	from red_pill.memento.agentic import annotation_quality as aq
	from red_pill.memento.agentic import prompts, runtime

	profiles = [args.profile_a] + ([args.profile_b] if args.profile_b else [])
	jsonl = (out / "ab_calls.jsonl").open("w", encoding="utf-8")
	records: List[Dict[str, Any]] = []

	def run_arm(arm: str, profile: str, chunks_by_unit: Dict[Path, List[str]]) -> None:
		os.environ["RP_LLM_MODEL"] = profile
		resolved = mr.resolve({"task": "annotate", "model": profile})
		n_ctx = int(resolved.n_ctx or 0)
		print(f"[ab] {arm}: {profile} n_ctx={n_ctx} — cargando")
		_unload()
		_warm(profile)
		_wait_loaded(profile, n_ctx)
		for unit_name, path in units:
			chunks = chunks_by_unit[path]
			for ci, chunk in enumerate(chunks):
				for rep in range(1, args.reps + 1):
					for prompt_id in ("annotate_work_user_v3", "annotate_social_user_v3"):
						rec = _call(runtime, prompts, chunk, prompt_id)
						raw = rec.pop("raw")
						(calls_dir / f"{arm}_{unit_name}_{ci}_{rep}_{prompt_id}.txt").write_text(raw, encoding="utf-8")
						m = _note_metrics(rec.pop("ideas"), aq)
						row = {
							"arm": arm,
							"profile": profile,
							"n_ctx": n_ctx,
							"unit": unit_name,
							"unit_path": str(path),
							"chunk": ci,
							"chunks": len(chunks),
							"rep": rep,
							**rec,
							**m,
						}
						jsonl.write(json.dumps(row, ensure_ascii=False) + "\n")
						jsonl.flush()
						records.append(row)
						print(
							f"[ab] {arm} {unit_name}#{ci}/{len(chunks)} r{rep} {prompt_id.split('_')[1]} "
							f"{row['chars']}ch → notas={row['notes']} fr={row['stats'].get('finish_reason')} "
							f"cap={row['stats'].get('prompt_capped')} {row['wall_s']}s err={row['error'] or '-'}"
						)

	chunks_plain = {p: [p.read_text(encoding="utf-8")] for _, p in units}
	chunks_split = (
		{
			p: balanced_chunks(p.read_text(encoding="utf-8"), args.chunk_chars)
			for _, p in units
		}
		if args.chunk_chars
		else {}
	)

	run_arm("A", args.profile_a, chunks_plain)
	if args.profile_b:
		run_arm("B", args.profile_b, chunks_plain)
	if args.chunk_chars:
		run_arm("C", args.profile_a, chunks_split)

	jsonl.close()
	_write_report(out / "AB.md", units, records, args)
	print(f"[ab] listo: {out/'AB.md'}")
	return 0


def _write_report(path: Path, units, records: List[Dict[str, Any]], args) -> None:
	arms = sorted({r["arm"] for r in records})
	lines = [
		"# annotate — A/B de contexto",
		"",
		f"- reps: {args.reps} · unidades: {', '.join(n for n, _ in units)}",
		f"- brazos: " + " · ".join(f"{a}={next(r['profile'] for r in records if r['arm']==a)}" for a in arms),
		"",
		"`notas/unidad` suma los dos prompts y todos los trozos de una repetición (la mediana es sobre reps).",
		"",
		"| brazo | unidad | trozos | chars | llamadas | err | trunc | cap | prompt_tok | notas/unidad | notas/llamada | 1ª pers. | voz | inglés | s/unidad |",
		"|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
	]
	groups: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = {}
	for r in records:
		groups.setdefault((r["arm"], r["unit"], r["chunks"]), []).append(r)
	for key in sorted(groups):
		arm, unit, chunks = key
		rows = groups[key]
		by_rep: Dict[int, List[Dict[str, Any]]] = {}
		for r in rows:
			by_rep.setdefault(r["rep"], []).append(r)
		per_unit_notes = [sum(x["notes"] for x in rs) for rs in by_rep.values()]
		per_unit_secs = [sum(x["wall_s"] for x in rs) for rs in by_rep.values()]
		ptoks = [r["stats"].get("prompt_tokens") for r in rows if r["stats"].get("prompt_tokens")]
		voice = sum(r["flags"].get("voice", 0) for r in rows)
		notes = sum(r["notes"] for r in rows)
		fp = sum(r["first_person"] for r in rows)
		lines.append(
			f"| {arm} | {unit} | {chunks} | {round(statistics.median([r['chars'] for r in rows]))} | {len(rows)} | "
			f"{sum(1 for r in rows if r['error'])} | {sum(1 for r in rows if r['truncated'])} | "
			f"{sum(1 for r in rows if r['stats'].get('prompt_capped'))} | "
			f"{round(statistics.median(ptoks)) if ptoks else '-'} | "
			f"{round(statistics.median(per_unit_notes), 1) if per_unit_notes else 0} | "
			f"{round(notes / max(1, len(rows)), 1)} | "
			f"{round(100 * fp / max(1, notes))}% | {voice} | "
			f"{round(100 * sum(r['english'] for r in rows) / max(1, notes))}% | "
			f"{round(statistics.median(per_unit_secs), 1) if per_unit_secs else 0} |"
		)
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
	raise SystemExit(main())
