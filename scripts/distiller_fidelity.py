#!/usr/bin/env python3
"""
Distiller fidelity eval — does the summary capture BOTH sides of the exchange?

The format bake-off (distiller_bakeoff.py) is a tie between hermes_8b and
granite_8b, but Granite once summarized only the user's premise and dropped the
assistant's reply. This eval isolates that: each probe is an interaction where
the USER and the ASSISTANT each contribute DISTINCT substance, and we check —
deterministically, via per-side keyword coverage — whether the summary reflects
both. It also compares a BASE prompt against a TUNED prompt that explicitly
demands both sides, to see if prompt tuning fixes the gap.

Self-contained (no red_pill deps) so it runs under the daemon's CUDA venv (GPU),
via `~/.local/share/red-pill/daemon/.venv/bin/python`, or the project venv (CPU).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [FIDELITY] %(message)s")
logger = logging.getLogger("fidelity")

_KNOWN_GGUF = {
	"hermes_8b": "Hermes-3-Llama-3.1-8B.Q4_K_M.gguf",
	"granite_8b": "Granite-4.1-8B-Q4_K_M.gguf",
	"piaget_8b": "Piaget-8B-Q4_K_M.gguf",
	"qwen35_9b": "Qwen3.5-9B-Q4_K_M.gguf",
}

_BASE_PROMPT = (
	"Distill the interaction into ONLY a valid JSON object with keys: "
	"summary (Spanish, concise), emotion (one of: joy, sadness, fear, disgust, anger, anxiety, envy, "
	"embarrassment, ennui, nostalgia, neutral), intensity (float 0.0-1.0), category ('work' or 'social'). "
	"No markdown, no reasoning, no extra text. /no_think"
)

_TUNED_PROMPT = (
	_BASE_PROMPT
	+ " The 'summary' MUST capture BOTH the user's point/question AND the assistant's response, "
	"correction, or decision — never only one side. One or two sentences."
)

# Each probe: distinct user vs assistant substance, and the keyword groups that
# signal each side was captured (present = any token in the group appears).
PROBES: List[Dict[str, Any]] = [
	{
		"key": "philosophical",
		"user": "no somos nuestros recuerdos, lo que nos define son nuestros actos, ¿no crees?",
		"assistant": "discrepo en parte; sin memoria no hay continuidad del yo que actúa, los actos sueltos no hacen identidad.",
		"user_terms": ["acto", "define", "definen"],
		"asst_terms": ["discrep", "desacuerdo", "memoria", "continuidad", "matiz", "sin embargo", "pero", "no hacen identidad"],
	},
	{
		"key": "caching",
		"user": "creo que deberíamos cachear los embeddings en disco para acelerar el arranque.",
		"assistant": "cuidado: el caché en disco se corrompe si cambia el modelo; mejor invalidarlo por hash del modelo.",
		"user_terms": ["cach", "disco", "arranqu", "acelerar"],
		"asst_terms": ["corromp", "invalid", "hash", "cuidado", "riesgo", "cambia el modelo"],
	},
	{
		"key": "db_decision",
		"user": "¿migramos a Postgres o seguimos con SQLite?",
		"assistant": "seguimos con SQLite por ahora; el volumen no justifica Postgres y añadiría operaciones.",
		"user_terms": ["postgres", "migra"],
		"asst_terms": ["no justifica", "volumen", "por ahora", "operacion", "añad", "seguimos"],
	},
]


def extract_summary(raw: str) -> str:
	match = re.search(r"\{[\s\S]*\}", raw or "")
	if not match:
		return ""
	try:
		obj = json.loads(match.group(0))
		return str(obj.get("summary", "")) if isinstance(obj, dict) else ""
	except Exception:
		return ""


def side_covered(summary: str, terms: List[str]) -> bool:
	low = summary.lower()
	return any(t in low for t in terms)


def score_fidelity(summary: str, probe: Dict[str, Any]) -> Dict[str, Any]:
	u = side_covered(summary, probe["user_terms"])
	a = side_covered(summary, probe["asst_terms"])
	return {"user_side": u, "asst_side": a, "both_sides": u and a, "summary": summary}


def run(name: str, model_path: Path, ngl: int, n_ctx: int, max_tokens: int) -> Dict[str, List[Dict[str, Any]]]:
	from llama_cpp import Llama

	logger.info(f"Loading {name} (ngl={ngl})...")
	llm = Llama(model_path=str(model_path), n_ctx=n_ctx, n_gpu_layers=ngl, verbose=False)
	out: Dict[str, List[Dict[str, Any]]] = {"base": [], "tuned": []}
	for label, sys_prompt in (("base", _BASE_PROMPT), ("tuned", _TUNED_PROMPT)):
		for probe in PROBES:
			user_msg = f"USER: {probe['user']} ASSISTANT: {probe['assistant']}"
			t0 = time.time()
			try:
				resp = llm.create_chat_completion(
					messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_msg}],
					temperature=0.1,
					max_tokens=max_tokens,
				)
				summary = extract_summary(resp["choices"][0]["message"]["content"])
			except Exception as e:
				summary = f"[ERROR] {e}"
			res = score_fidelity(summary, probe)
			res.update({"probe": probe["key"], "prompt": label, "latency_s": round(time.time() - t0, 2)})
			out[label].append(res)
			logger.info(f"  {name}/{label}/{probe['key']}: both={res['both_sides']} (u={res['user_side']} a={res['asst_side']})")
	del llm
	return out


def render(results: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> str:
	lines = ["# Distiller Fidelity Eval (both-sides coverage)", "", "Does the summary reflect BOTH the user and the assistant? BASE vs TUNED prompt.", ""]
	lines += ["| Model | Prompt | Both-sides | User-side | Asst-side |", "|---|---|---|---|---|"]
	for name, byp in results.items():
		for label in ("base", "tuned"):
			rows = byp.get(label, [])
			n = len(rows) or 1
			lines.append(
				f"| {name} | {label} | {sum(r['both_sides'] for r in rows)}/{n} | {sum(r['user_side'] for r in rows)}/{n} | {sum(r['asst_side'] for r in rows)}/{n} |"
			)
	lines.append("")
	for name, byp in results.items():
		lines.append(f"## {name}")
		for label in ("base", "tuned"):
			lines.append(f"### {label}")
			for r in byp.get(label, []):
				flag = "✓" if r["both_sides"] else ("✗ only-user" if r["user_side"] else "✗ only-asst" if r["asst_side"] else "✗ neither")
				lines.append(f"- [{r['probe']}] {flag}: {r['summary'][:180]}")
			lines.append("")
	return "\n".join(lines)


def main() -> None:
	parser = argparse.ArgumentParser(description="Distiller fidelity (both-sides) eval.")
	parser.add_argument("--models", default="hermes_8b,granite_8b")
	parser.add_argument("--n-gpu-layers", type=int, default=-1, help="-1 GPU / 0 CPU / N hybrid (needs CUDA llama-cpp for GPU).")
	parser.add_argument("--n-ctx", type=int, default=4096)
	parser.add_argument("--max-tokens", type=int, default=512)
	parser.add_argument("--models-dir", default=str(Path("~/.local/share/red-pill/models").expanduser()))
	parser.add_argument("--out", default="docs/BENCHMARKS/DISTILLER_FIDELITY.md")
	args = parser.parse_args()

	models_dir = Path(args.models_dir)
	results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
	for name in [n.strip() for n in args.models.split(",") if n.strip()]:
		path: Optional[Path] = None
		if name in _KNOWN_GGUF:
			cand = models_dir / _KNOWN_GGUF[name]
			path = cand if cand.exists() else None
		if not path:
			logger.warning(f"{name}: GGUF not found in {models_dir}, skipping.")
			continue
		try:
			results[name] = run(name, path, args.n_gpu_layers, args.n_ctx, args.max_tokens)
		except Exception as e:
			logger.error(f"{name}: FAILED — {e}")

	if not results:
		logger.error("No models runnable.")
		return
	out_path = Path(args.out)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(render(results), encoding="utf-8")
	(out_path.with_suffix(".json")).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
	logger.info(f"Wrote {out_path}")


if __name__ == "__main__":
	main()
