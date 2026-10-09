#!/usr/bin/env python3
"""bakeoff_bonsai_matrix.py — matriz runtime × modelo (RFC-HARNESS-003, corte 3).

Corre la MISMA batería de probes sobre modelos servidos por runtimes distintos:

- bonsai_2_27b   → RuntimeBattleRunner (fork PrismML, llama-server dedicado)
- granite_4_2_8b → BattleRunner (llama-cpp-python, runtime stock)

La medición es del PUESTO DE REFERENCIA — recalibrar por equipo
(docs/CORE/CONVENTIONS.md §10.7).

Uso: PYTHONPATH=src <venv> scripts/bakeoff_bonsai_matrix.py
Salida: docs/BENCHMARKS/YYYY-MM-DD-RUNTIME_MATRIX_BAKEOFF.md (+ .jsonl)
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from model_battle_lib import Probe, format_summary, runner_for, write_jsonl  # noqa: E402

from red_pill.core.model_runtime import extract_thinking  # noqa: E402


def _strip_thinking(raw: str) -> str:
	"""Separador canónico del repo (model_runtime.extract_thinking) + CLI marker."""
	clean = re.sub(r"\[Start thinking\][\s\S]*?(?:\[End thinking\]|$)", "", raw, count=1)
	_, answer = extract_thinking(clean)
	return answer


def _first_json(raw: str):
	idx = raw.find("{")
	if idx == -1:
		return None
	try:
		obj, _ = json.JSONDecoder().raw_decode(raw[idx:])
		return obj
	except Exception:
		return None


def _v_math(raw: str) -> dict:
	return {"valid": "220" in raw}


def _v_json(raw: str) -> dict:
	obj = _first_json(_strip_thinking(raw))
	ok = isinstance(obj, dict) and {"pais", "capital"} <= set(obj.keys())
	return {"valid": ok, "keys": sorted(obj.keys()) if isinstance(obj, dict) else []}


def _v_frases(raw: str) -> dict:
	text = _strip_thinking(raw).strip()
	n = len(re.findall(r"[.!?](?:\s|$)", text))
	return {"valid": 2 <= n <= 4, "frases": n}


PROBES = [
	Probe(
		name="math",
		system_prompt="Eres un asistente útil.",
		user_message="Un tren viaja a 80 km/h durante 2 horas y 45 minutos. ¿Cuántos km recorre? Responde solo con el número.",
		validator=_v_math,
		max_tokens=2048,
		temperature=1.0,
	),
	Probe(
		name="json",
		system_prompt="Eres un asistente útil.",
		user_message="Devuelve SOLO un JSON válido con las claves pais, capital, poblacion_millones para España. Sin texto alrededor.",
		validator=_v_json,
		max_tokens=2048,
		temperature=1.0,
	),
	Probe(
		name="frases",
		system_prompt="Eres un asistente útil.",
		user_message="Escribe exactamente 3 frases en español sobre el mar Mediterráneo. No uses listas ni títulos.",
		validator=_v_frases,
		max_tokens=2048,
		temperature=1.0,
	),
]

MODELS = [
	("bonsai_2_27b", dict(n_ctx=24576)),
	("granite_4_2_8b", dict(n_ctx=8192)),
]


def main() -> int:
	all_results = {}
	for name, kwargs in MODELS:
		print(f"\n########## {name} ##########", flush=True)
		try:
			runner = runner_for(name, **kwargs)
		except Exception as e:
			print(f"[{name}] no se pudo levantar: {e}", flush=True)
			continue
		try:
			all_results[name] = runner.run_all(PROBES)
		finally:
			runner.close()

	day = time.strftime("%Y-%m-%d")
	out_dir = REPO / "docs" / "BENCHMARKS"
	out_dir.mkdir(parents=True, exist_ok=True)
	out_md = out_dir / f"{day}-RUNTIME_MATRIX_BAKEOFF.md"
	lines = [
		f"# Runtime matrix bake-off — {time.strftime('%Y-%m-%d %H:%M')}",
		"",
		"> Matriz runtime × modelo (RFC-HARNESS-003): el mismo harness sirve cada",
		"> modelo por su runtime anclado — Bonsai 2 27B PTQ1_0 exige el fork",
		"> PrismML (`llama_cpp_prism`); Granite corre por el runtime stock.",
		">",
		"> Medidas del PUESTO DE REFERENCIA (RTX 5070 Laptop 8 GB, sm_120a) —",
		"> recalibrar por equipo (docs/CORE/CONVENTIONS.md §10.7).",
		"",
		"```",
		format_summary(all_results),
		"```",
		"",
	]
	for name, results in all_results.items():
		lines.append(f"## {name}")
		for r in results:
			lines.append(f"- {r.probe_name}: {json.dumps(r.validation, ensure_ascii=False)} | {r.latency_s:.1f}s")
			lines.append(f"  - out: {r.raw_output[:300].replace(chr(10), ' ')}")
		lines.append("")
	out_md.write_text("\n".join(lines), encoding="utf-8")

	flat = [r for rs in all_results.values() for r in rs]
	write_jsonl(flat, out_md.with_suffix(".jsonl"))
	print(f"\n[out] {out_md}", flush=True)
	return 0


if __name__ == "__main__":
	sys.exit(main())
