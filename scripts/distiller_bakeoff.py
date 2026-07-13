#!/usr/bin/env python3
"""
Distiller bake-off — measure the aptitudes of each candidate distiller model.

The sleep cycle's distiller must do several jobs at once: strict JSON, faithful
Spanish summaries, sane emotion/intensity labels, and NOT dramatize log noise.
This harness runs an aptitude battery against each candidate GGUF and scores the
outputs with deterministic heuristics, so the operator picks the winner from data
instead of vibes.

Candidates (download first with the model download step):
- qwen35_9b : Qwen3.5-9B      (generalist, multilingual, large ctx)
- beck_8b   : Beck-8B         (Piaget finetune: psychology/philosophy reasoning)
- piaget_8b : Piaget-8B       (Qwen3-8B + psych/philo LoRA)
- hermes_8b : Hermes-3-8B     (classic Llama, control)
- samantha  : Samantha-7B     (legacy, control)

Scoring is heuristic (JSON-parses, language, <think> tags, prompt-echo, valid
emotion/intensity, latency). It ranks candidates but the operator confirms.

Run:  uv run python scripts/distiller_bakeoff.py --models qwen35_9b,beck_8b,piaget_8b,hermes_8b
Defaults to CPU (n_gpu_layers=0) to avoid contending with the live daemon's VRAM.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [BAKEOFF] %(message)s")
logger = logging.getLogger("bakeoff")

_VALID_EMOTIONS = {"joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"}
_SPANISH_MARKERS = ("á", "é", "í", "ó", "ú", "ñ", "¿", "¡")
_SPANISH_STOPWORDS = {"de", "la", "el", "que", "los", "con", "por", "una", "es", "se", "en", "y", "un", "para"}

_DISTILL_SYSTEM = (
	"Distill the interaction into ONLY a valid JSON object with keys: "
	"summary (Spanish, concise), emotion (one of: joy, sadness, fear, disgust, anger, anxiety, envy, "
	"embarrassment, ennui, nostalgia, neutral), intensity (float 0.0-1.0), category ('work' or 'social'). "
	"No markdown, no reasoning, no extra text. /no_think"
)

# Aptitude battery — one probe per dimension we care about.
PROMPTS: List[Dict[str, str]] = [
	{
		"key": "technical",
		"aptitude": "Technical distillation (work, strict JSON)",
		"user": "USER: hemos arreglado el bug de tree_hash en pure-mls, 248 tests verdes. ASSISTANT: confirmado, era el leaf_index omitido en la RFC 9420 §7.8.",
	},
	{
		"key": "philosophical",
		"aptitude": "Narrative/philosophical (social, Spanish fidelity)",
		"user": "USER: no somos nuestros recuerdos, lo que nos define son nuestros actos, ¿no crees? ASSISTANT: discrepo en parte; sin memoria no hay continuidad del yo que actúa, los actos sueltos no hacen identidad.",
	},
	{
		"key": "noise",
		"aptitude": "Noise culling (should be neutral, low intensity)",
		"user": "USER: [pytest] FAILED tests/test_lint.py::test_ruff_check - AssertionError ASSISTANT: es el linter, reejecuta con --fix.",
	},
	{
		"key": "emotional",
		"aptitude": "Emotional labeling (charged interaction)",
		"user": "USER: llevo tres noches sin dormir peleando con el entrenamiento y hoy por fin ha convergido, estoy eufórico. ASSISTANT: te lo has ganado, Joan; ese pico de pérdida bajando es tuyo.",
	},
]


def detect_language(text: str) -> str:
	"""Cheap ES/EN heuristic for the summary field."""
	if not text:
		return "empty"
	low = text.lower()
	if any(m in low for m in _SPANISH_MARKERS):
		return "es"
	words = set(re.findall(r"[a-záéíóúñ]+", low))
	return "es" if len(words & _SPANISH_STOPWORDS) >= 2 else "en"


def extract_json(text: str) -> Optional[Dict[str, Any]]:
	match = re.search(r"\{[\s\S]*\}", text or "")
	if not match:
		return None
	try:
		obj = json.loads(match.group(0))
		return obj if isinstance(obj, dict) else None
	except Exception:
		return None


def score_output(raw: str) -> Dict[str, Any]:
	"""Deterministic heuristics scoring a single distillation output."""
	from red_pill.metabolism.sleep import _is_template_echo

	obj = extract_json(raw)
	summary = str(obj.get("summary", "")) if obj else ""
	emotion = str(obj.get("emotion", "")).lower() if obj else ""
	intensity = obj.get("intensity") if obj else None
	try:
		intensity_ok = intensity is not None and 0.0 <= float(intensity) <= 1.0
	except (TypeError, ValueError):
		intensity_ok = False
	return {
		"json_ok": obj is not None,
		"has_keys": bool(obj) and all(k in obj for k in ("summary", "emotion", "intensity", "category")),
		"summary_lang": detect_language(summary),
		"has_think_tags": "<think>" in (raw or "").lower(),
		"echoes_prompt": _is_template_echo(summary) if summary else True,
		"emotion_valid": emotion in _VALID_EMOTIONS,
		"intensity_valid": intensity_ok,
		"summary_len": len(summary),
	}


def _load_profiles() -> Dict[str, Any]:
	import red_pill.config as cfg  # noqa: F401
	from red_pill.core.model_registry import ModelRegistry

	ModelRegistry._load_profiles()
	return ModelRegistry._profiles_cache or {}


def _resolve_model_path(profile: Dict[str, Any]) -> Optional[Path]:
	from red_pill.core.paths import get_models_dir

	raw = profile.get("model_path", "")
	candidates = [Path(raw), get_models_dir() / Path(raw).name]
	for c in candidates:
		if c.exists():
			return c
	return None


def run_model(name: str, model_path: Path, n_gpu_layers: int, n_ctx: int) -> List[Dict[str, Any]]:
	from llama_cpp import Llama

	logger.info(f"Loading {name} from {model_path} (ngl={n_gpu_layers}, ctx={n_ctx})...")
	llm = Llama(model_path=str(model_path), n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)
	results = []
	for probe in PROMPTS:
		t0 = time.time()
		try:
			out = llm.create_chat_completion(
				messages=[{"role": "system", "content": _DISTILL_SYSTEM}, {"role": "user", "content": probe["user"]}],
				temperature=0.1,
				max_tokens=512,
			)
			raw = out["choices"][0]["message"]["content"]
		except Exception as e:
			raw = f"[ERROR] {e}"
		score = score_output(raw)
		score["latency_s"] = round(time.time() - t0, 2)
		results.append({"probe": probe["key"], "aptitude": probe["aptitude"], "raw": raw, "score": score})
		logger.info(f"  {name}/{probe['key']}: json={score['json_ok']} lang={score['summary_lang']} think={score['has_think_tags']} {score['latency_s']}s")
	del llm
	return results


def render_markdown(all_results: Dict[str, List[Dict[str, Any]]]) -> str:
	lines = ["# Distiller Bake-off Results", "", "Heuristic aptitude scores per candidate. Operator confirms the winner.", ""]
	# Aggregate table
	lines += ["## Aggregate (per model, across the battery)", "", "| Model | JSON ok | Keys ok | Spanish | No <think> | No echo | Emotion ok | Avg latency |", "|---|---|---|---|---|---|---|---|"]
	for name, results in all_results.items():
		n = len(results) or 1
		agg = {
			"json": sum(r["score"]["json_ok"] for r in results),
			"keys": sum(r["score"]["has_keys"] for r in results),
			"es": sum(r["score"]["summary_lang"] == "es" for r in results),
			"nothink": sum(not r["score"]["has_think_tags"] for r in results),
			"noecho": sum(not r["score"]["echoes_prompt"] for r in results),
			"emo": sum(r["score"]["emotion_valid"] for r in results),
			"lat": round(sum(r["score"]["latency_s"] for r in results) / n, 2),
		}
		lines.append(f"| {name} | {agg['json']}/{n} | {agg['keys']}/{n} | {agg['es']}/{n} | {agg['nothink']}/{n} | {agg['noecho']}/{n} | {agg['emo']}/{n} | {agg['lat']}s |")
	lines.append("")
	# Raw outputs
	for name, results in all_results.items():
		lines.append(f"## {name}")
		for r in results:
			lines += [f"### {r['probe']} — {r['aptitude']}", "```json", r["raw"].strip()[:1200], "```", f"score: `{json.dumps(r['score'])}`", ""]
	return "\n".join(lines)


def main() -> None:
	parser = argparse.ArgumentParser(description="Distiller bake-off aptitude harness.")
	parser.add_argument("--models", default="qwen35_9b,beck_8b,piaget_8b,hermes_8b", help="Comma-separated profile names.")
	parser.add_argument("--n-gpu-layers", type=int, default=0, help="0 = CPU (safe vs live daemon VRAM). Bump if VRAM is free.")
	parser.add_argument("--n-ctx", type=int, default=4096)
	parser.add_argument("--out", default="docs/BENCHMARKS/DISTILLER_BAKEOFF.md")
	args = parser.parse_args()

	profiles = _load_profiles()
	names = [n.strip() for n in args.models.split(",") if n.strip()]

	all_results: Dict[str, List[Dict[str, Any]]] = {}
	for name in names:
		profile = profiles.get(name)
		if not profile:
			logger.warning(f"{name}: no profile found, skipping.")
			continue
		path = _resolve_model_path(profile)
		if not path:
			logger.warning(f"{name}: GGUF not downloaded yet ({profile.get('model_path')}), skipping.")
			continue
		all_results[name] = run_model(name, path, args.n_gpu_layers, args.n_ctx)

	if not all_results:
		logger.error("No models were runnable (none downloaded?). Nothing to write.")
		return

	out_path = Path(args.out)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(render_markdown(all_results), encoding="utf-8")
	(out_path.with_suffix(".json")).write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
	logger.info(f"Wrote {out_path} and {out_path.with_suffix('.json')}")


if __name__ == "__main__":
	main()
