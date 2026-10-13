#!/usr/bin/env python3
"""bench_audio.py — banco A/B de audio generativo LOCAL (voz / música / SFX).

Un ELEMENTO = UN motor. Cada motor recorre sus piezas (matriz fija por versión),
genera WAV, mide tiempo/VRAM/duración y guarda `metrics.jsonl`. Reanudable por
pieza (si el WAV existe, se salta). Fail-soft lo gestiona el element_job.

Motores (dispatch por id):
		- kokoro_voice      : KPipeline (kokoro) — TTS Apache-2.0, 54 voces
		- chatterbox_voice  : ChatterboxTTS    — TTS MIT, emoción/clonación
		- ace_step_music    : AceStepPipeline  (diffusers) — música MIT, con voz
		- stable_audio_sfx  : StableAudioPipeline (diffusers) — SFX/ambiente

Rutas configurables: AUDIO_FORGE_HOME (def ~/opt/audio-forge), HF_HOME.

Uso (normalmente vía element_job; manual para debug):
		python bench_audio.py --list-models
		python bench_audio.py --element                       # lee RP_ELEMENT
		python bench_audio.py --models kokoro_voice --pieces en_news
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BENCH_JSON = Path(__file__).resolve().parent / "soundgenres.json"

MODELS = {
	"kokoro_voice": {
		"backend": "kokoro",
		"kinds": ["voice"],
		"license": "apache-2.0",
		"note": "Kokoro-82M — TTS ligero, 54 voces, corre en CPU/GPU. Sin clonación.",
	},
	"chatterbox_voice": {
		"backend": "chatterbox",
		"kinds": ["voice"],
		"license": "mit",
		"note": "Chatterbox 0.5B — TTS con clonación/emoción (exaggeration).",
	},
	"moss_sfx": {
		"backend": "moss",
		"kinds": ["sfx"],
		"license": "apache-2.0",
		"note": "MOSS-SoundEffect v2.0 (1.3B DiT+DAC+Qwen3) — SFX/ambiente: naturaleza, animales, urbano. 48 kHz.",
	},
	"dasheng_scene": {
		"backend": "dasheng",
		"kinds": ["scene"],
		"license": "apache-2.0",
		"note": "Dasheng-AudioGen (~6GB, Qwen3-1.7B+DiT) — escena mixta: voz+música+SFX+ambiente en 16 kHz.",
	},
}


def _forge_home() -> Path:
	return Path(os.environ.get("AUDIO_FORGE_HOME") or (Path.home() / "opt" / "audio-forge"))


def _setup_caches() -> None:
	os.environ.setdefault("HF_HOME", str(_forge_home() / "hf-cache"))


def _load_bench() -> dict:
	return json.loads(BENCH_JSON.read_text(encoding="utf-8"))


# ── utilidades WAV ──────────────────────────────────────────────────────────
def _save_wav(path: Path, audio, sr: int) -> None:
	import numpy as np
	import soundfile as sf
	import torch

	if isinstance(audio, torch.Tensor):
		audio = audio.detach().cpu().float().numpy()
	a = np.asarray(audio, dtype="float32")
	if a.ndim == 2 and a.shape[0] <= 2 and a.shape[0] < a.shape[1]:
		a = a.T  # (canales, n) -> (n, canales)
	peak = float(np.max(np.abs(a))) or 1.0
	if peak > 1.0:
		a = a / peak
	sf.write(str(path), a, sr)


# ── carga/generación por motor ──────────────────────────────────────────────
def _gen_kokoro(piece, size_hint=None):
	import numpy as np

	pipe = _kokoro_pipeline(piece["lang"])
	chunks = []
	for _gs, _ps, audio in pipe(piece["text"], voice=piece["voice"]):
		chunks.append(audio if hasattr(audio, "shape") else np.asarray(audio))
	audio = np.concatenate([np.asarray(c).reshape(-1) for c in chunks])
	return audio, 24000


_KOKORO_CACHE: dict = {}


def _kokoro_pipeline(lang_code: str):
	from kokoro import KPipeline

	if lang_code not in _KOKORO_CACHE:
		_KOKORO_CACHE[lang_code] = KPipeline(lang_code=lang_code)
	return _KOKORO_CACHE[lang_code]


def _gen_chatterbox(piece, size_hint=None):
	from chatterbox.tts import ChatterboxTTS

	global _CHATTERBOX
	if "_CHATTERBOX" not in globals():
		_CHATTERBOX = ChatterboxTTS.from_pretrained(device="cuda")
	wav = _CHATTERBOX.generate(piece["text"], exaggeration=0.5)
	return wav.squeeze(0).numpy() if hasattr(wav, "squeeze") else wav, _CHATTERBOX.sr


def _gen_moss(piece, size_hint=None):
	import os

	os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")  # evita compile/Triton en sm_120
	from moss_soundeffect_v2 import MossSoundEffectPipeline

	global _MOSS
	if "_MOSS" not in globals():
		import torch

		# 8 GB: cargar en CPU y activar la gestión de VRAM por etapa del engine
		# DiffSynth (onload/offload de text_encoder/DiT/VAE según la unidad).
		_MOSS = MossSoundEffectPipeline.from_pretrained("OpenMOSS-Team/MOSS-SoundEffect-v2.0", torch_dtype=torch.bfloat16, device="cpu")
		try:
			_MOSS.engine.enable_cpu_offload()
		except Exception:
			_MOSS.engine.vram_management_enabled = True
		_MOSS.engine.device = "cuda"
	audio = _MOSS(
		prompt=piece["prompt"],
		seconds=float(piece.get("duration", 10)),
		num_inference_steps=100,
		cfg_scale=4.0,
	)
	a = audio[0] if hasattr(audio, "ndim") and audio.ndim == 3 else audio
	sr = getattr(_MOSS, "sampling_rate", None) or getattr(getattr(_MOSS, "vae", None), "sampling_rate", 48000)
	return a, int(sr)


def _gen_dasheng(piece, size_hint=None):
	import torch
	from transformers import AutoModel

	global _DSG
	if "_DSG" not in globals():
		_DSG = AutoModel.from_pretrained("mispeech/Dasheng-AudioGen", trust_remote_code=True, dtype=torch.bfloat16).cuda()
	kw = {k: piece[k] for k in ("caption", "speech", "asr", "sfx", "music", "env") if piece.get(k)}
	prompt = _DSG.compose_prompt(**kw)
	audio = _DSG.generate(prompt, num_steps=25, guidance_scale=5.0)
	return audio, 16000


_DISPATCH = {
	"kokoro": _gen_kokoro,
	"chatterbox": _gen_chatterbox,
	"moss": _gen_moss,
	"dasheng": _gen_dasheng,
}


def _pieces_for(model_id: str, bench: dict) -> list:
	cfg = MODELS[model_id]
	pieces = []
	for kind in cfg["kinds"]:
		for p in bench.get(kind, []):
			pieces.append({**p, "kind": kind})
	return pieces


def _run_model(model_id: str, bench: dict, out_dir: Path, only: set | None) -> int:
	import torch

	out_dir.mkdir(parents=True, exist_ok=True)
	metrics = out_dir / "metrics.jsonl"
	cfg = MODELS[model_id]
	pieces = _pieces_for(model_id, bench)
	if only:
		pieces = [p for p in pieces if p["id"] in only]

	print(f"##### {model_id} ({cfg['backend']}) — {len(pieces)} piezas #####", flush=True)
	gen = _DISPATCH[cfg["backend"]]
	load_s = None
	n_ok = 0
	n_skip = 0
	for p in pieces:
		wav = out_dir / f"{model_id}__{p['id']}.wav"
		if wav.exists():
			print(f"  [skip] {wav.name}", flush=True)
			n_skip += 1
			continue
		try:
			if torch.cuda.is_available():
				torch.cuda.reset_peak_memory_stats()
			t0 = time.perf_counter()
			audio, sr = gen(p)
			wall = time.perf_counter() - t0
			load_s = load_s or wall  # primera pieza incluye carga
			peak = torch.cuda.max_memory_allocated() / (1024**2) if torch.cuda.is_available() else 0.0
			_save_wav(wav, audio, sr)
			rec = {
				"model": model_id,
				"piece": p["id"],
				"kind": p["kind"],
				"sr": int(sr),
				"wall_s": round(wall, 2),
				"peak_mb": round(peak, 1),
				"wav": wav.name,
			}
			with metrics.open("a", encoding="utf-8") as f:
				f.write(json.dumps(rec, ensure_ascii=False) + "\n")
			n_ok += 1
			print(f"  [{p['id']}] {wall:.1f}s  sr={sr}  peak {peak:.0f}MB", flush=True)
		except Exception as e:  # noqa: BLE001 — fail-soft por pieza
			print(f"  [{p['id']}] FALLO: {e}", flush=True)
			with metrics.open("a", encoding="utf-8") as f:
				f.write(json.dumps({"model": model_id, "piece": p["id"], "error": str(e)}, ensure_ascii=False) + "\n")
	# Viable si algo salió o ya existía (resume); si NADA, falla.
	return 0 if (n_ok + n_skip) > 0 else 1


# ── CLI ─────────────────────────────────────────────────────────────────────
def main() -> int:
	ap = argparse.ArgumentParser(description="Banco A/B de audio generativo local")
	ap.add_argument("--list-models", action="store_true")
	ap.add_argument("--element", action="store_true")
	ap.add_argument("--models", help="lista csv de ids")
	ap.add_argument("--pieces", help="lista csv de ids de pieza")
	ap.add_argument("--out", default=str(_forge_home() / "output"))
	args = ap.parse_args()

	_setup_caches()
	bench = _load_bench()

	if args.list_models:
		print(json.dumps([{"model": m} for m in MODELS], ensure_ascii=False))
		return 0

	if args.element:
		raw = os.environ.get("RP_ELEMENT") or ""
		try:
			element = json.loads(raw)
		except Exception as e:
			print(f"RP_ELEMENT inválido ({e}): {raw!r}", flush=True)
			return 1
		args.models = str(element.get("model") or "")

	models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
	if not models:
		print("Nada que generar: usa --models o --element")
		return 1
	for m in models:
		if m not in MODELS:
			print(f"motor desconocido: {m} (válidos: {', '.join(MODELS)})")
			return 1

	only = {p.strip() for p in args.pieces.split(",") if p.strip()} if args.pieces else None
	out_dir = Path(args.out)
	rc = 0
	for model_id in models:
		rc |= _run_model(model_id, bench, out_dir, only)
	print(f"[out] {out_dir}", flush=True)
	return rc


if __name__ == "__main__":
	sys.exit(main())
