#!/usr/bin/env python3
"""bench_imagegen.py — banco A/B de generación de imagen LOCAL.

Clasifica modelos texto→imagen por TIPO DE ARTE (no descarta ninguno: cada uno
hace las cosas a su manera, como el model_catalog clasifica los LLM por tarea).
Un ELEMENTO = UN modelo, que recorre la matriz fija de GÉNEROS × seeds. Mide
tiempo/imagen y VRAM pico, guarda PNG y un metrics.jsonl incremental.

Reanudable por género: si el PNG del par (modelo, género, seed) ya existe, se
salta (idempotente). Fail-soft lo gestiona el element_job (skip_exit_code).

Registro de modelos (DATOS, no código): el harness LEE cada modelo del elenco de
máquina `media_profiles.yaml` (la MISMA fuente que el router); su campo `backend`
elige el loader (diffusers / bonsai / …).

Rutas configurables (opción por defecto del puesto, override por entorno):
		IMAGE_FORGE_HOME          (def ~/opt/image-forge)  — venv + repo image-studio + caches
		REDPILL_IMAGE_MODELS_DIR  (def $XDG_DATA_HOME/red-pill/models/image)
		HF_HOME                   (def $IMAGE_FORGE_HOME/hf-cache)

Uso manual (lo normal es que lo invoque el element_job):
		python bench_imagegen.py --list-models
		python bench_imagegen.py --element                       # lee RP_ELEMENT
		python bench_imagegen.py --models flux2_klein --genres photo_portrait --seeds 42
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH_JSON = Path(__file__).resolve().parent / "benchgenres.json"

# ── Registro de modelos: DATOS, no código (CONVENTIONS §10.8.2) ──────────────
# El harness NO hardcodea modelos: los traduce desde el elenco de máquina
# (media_profiles.yaml, la MISMA fuente que consume el router). Añadir un modelo
# = añadir su entrada al YAML (backend + pipeline/weights/sampler), sin tocar
# código. El "cómo" de un runtime nuevo (p.ej. sd.cpp) vive en su backend + en
# runtimes.yaml (ver docs/CORE/MEDIA_MODELS.md).


def _media_profiles_path() -> Path:
	env = os.environ.get("REDPILL_MEDIA_PROFILES")
	if env:
		return Path(env)
	cfg = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
	return Path(cfg) / "red-pill" / "media_profiles.yaml"


def _load_media_models() -> dict:
	"""Traduce el elenco (`media_profiles.yaml`) a la forma que carga el harness.

	Cada modelo de imagen (modality=image) declara `backend` (dispatch) + sus
	params; aquí se normalizan a backend/pipeline/hf_id/steps/guidance/license
	(+ backend_name). Falla limpio si el elenco falta o está malformado.
	"""
	import yaml

	path = _media_profiles_path()
	try:
		data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
	except FileNotFoundError:
		raise RuntimeError(f"media_profiles.yaml no encontrado en {path} (copia examples/media_profiles.yaml.example)")
	except yaml.YAMLError as e:
		raise RuntimeError(f"media_profiles.yaml malformado en {path}: {e}")

	profiles = data.get("media_profiles") or {}
	models: dict = {}
	for mid, profile in profiles.items():
		if not isinstance(profile, dict) or profile.get("modality") != "image":
			continue
		backend = profile.get("backend")
		if not backend:
			continue  # sin `backend` declarado el harness no sabe cómo cargarlo
		sampler = profile.get("sampler") or {}
		entry = {
			"id": mid,
			"backend": backend,
			"pipeline": profile.get("pipeline"),
			"hf_id": profile.get("weights"),
			"steps": sampler.get("steps"),
			"guidance": sampler.get("guidance"),
			"license": (profile.get("license") or {}).get("id"),
			"note": profile.get("notes"),
		}
		if profile.get("backend_name"):
			entry["backend_name"] = profile["backend_name"]
		if backend == "sd_cpp":
			entry["runtime"] = profile.get("runtime") or "sd_cpp"
			entry["sampler_method"] = sampler.get("sampler") or "euler"
			entry["sd_cpp"] = profile.get("sd_cpp") or {}
		models[mid] = entry
	if not models:
		raise RuntimeError(f"media_profiles.yaml sin modelos de imagen cargables en {path}")
	return models


MODELS = _load_media_models()


def _runtimes_path() -> Path:
	env = os.environ.get("REDPILL_RUNTIMES")
	if env:
		return Path(env)
	cfg = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
	return Path(cfg) / "red-pill" / "runtimes.yaml"


def _resolve_runtime(runtime_id: str) -> dict:
	"""Resuelve un engine del registro de runtimes (~/.config/red-pill/runtimes.yaml)."""
	import yaml

	path = _runtimes_path()
	try:
		data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
	except FileNotFoundError:
		raise RuntimeError(f"runtimes.yaml no encontrado en {path} (copia examples/runtimes.yaml.example)")
	except yaml.YAMLError as e:
		raise RuntimeError(f"runtimes.yaml malformado en {path}: {e}")
	rt = (data.get("runtimes") or {}).get(runtime_id)
	if not rt:
		raise RuntimeError(f"runtime '{runtime_id}' no está declarado en {path}")
	return rt


def _resolve_sd_cpp(cfg: dict) -> dict:
	"""Resuelve binario (del runtime) + ficheros GGUF/safetensors (del elenco). Falla limpio."""
	rt = _resolve_runtime(cfg.get("runtime") or "sd_cpp")
	binary = Path(os.path.expanduser(str(rt.get("binary") or "")))
	if not binary.is_file():
		raise RuntimeError(f"sd.cpp: binario no encontrado {binary} (runtime '{cfg.get('runtime')}')")
	sd = cfg.get("sd_cpp") or {}
	paths = {k: Path(os.path.expanduser(str(sd.get(k) or ""))) for k in ("diffusion_model", "text_encoder", "vae")}
	for key, p in paths.items():
		if not p.is_file():
			raise RuntimeError(f"sd.cpp: {key} no encontrado {p} (modelo {cfg.get('id')})")
	env = dict(os.environ)
	for k, v in (rt.get("env") or {}).items():
		env[str(k)] = os.path.expanduser(str(v))
	return {"binary": binary, "paths": paths, "sd": sd, "rt": rt, "env": env, "cfg": cfg}


def _sd_cpp_generate(ctx: dict, prompt: str, seed: int, width: int, height: int):
	"""Ejecuta sd-cli (subprocess) y devuelve la PIL.Image del PNG resultante."""
	import subprocess
	import tempfile

	from PIL import Image

	cfg = ctx["cfg"]
	sd = ctx["sd"]
	with tempfile.TemporaryDirectory() as td:
		out = Path(td) / "out.png"
		cmd = [
			str(ctx["binary"]),
			"--diffusion-model", str(ctx["paths"]["diffusion_model"]),
			"--llm", str(ctx["paths"]["text_encoder"]),
			"--vae", str(ctx["paths"]["vae"]),
			"--backend", str(sd.get("backend_assign") or "te=cpu,diffusion=cuda0,vae=cuda0"),
			"--steps", str(cfg.get("steps") or 8),
			"--cfg-scale", str(cfg.get("guidance", 1.0)),
			"--sampling-method", str(cfg.get("sampler_method") or "euler"),
			"-W", str(width), "-H", str(height),
			"-s", str(seed),
			"-p", prompt,
			"-o", str(out),
		]
		if sd.get("sigmas"):
			cmd += ["--sigmas", str(sd["sigmas"])]
		cmd += [str(a) for a in (sd.get("extra_args") or [])]
		proc = subprocess.run(cmd, env=ctx["env"], capture_output=True, text=True)
		if proc.returncode != 0 or not out.is_file():
			tail = (proc.stderr or proc.stdout or "")[-2000:]
			raise RuntimeError(f"sd-cli falló (rc={proc.returncode}): {tail}")
		return Image.open(out).convert("RGB")


def _forge_home() -> Path:
	return Path(os.environ.get("IMAGE_FORGE_HOME") or (Path.home() / "opt" / "image-forge"))


def _models_dir() -> Path:
	env = os.environ.get("REDPILL_IMAGE_MODELS_DIR")
	if env:
		return Path(env)
	base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
	return Path(base) / "red-pill" / "models" / "image"


def _setup_caches() -> None:
	forge = _forge_home()
	os.environ.setdefault("HF_HOME", str(forge / "hf-cache"))
	os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")


def _load_bench() -> dict:
	return json.loads(BENCH_JSON.read_text(encoding="utf-8"))


def _diffusers_pipe_class(name: str):
	import diffusers

	cls = getattr(diffusers, name, None)
	if cls is None:
		raise RuntimeError(f"diffusers {diffusers.__version__} no expone {name} (¿falta install desde main?)")
	return cls


# ── Carga per-backend ───────────────────────────────────────────────────────
def _load_diffusers_4bit(cls, hf_id: str):
	"""Carga 4-bit probando las dos APIs de diffusers (varían por pipeline).

	- Flux2KleinPipeline acepta `transformers.BitsAndBytesConfig`.
	- ZImagePipeline exige `diffusers.PipelineQuantizationConfig`.
	Devuelve el pipe o None si ninguna API aplica (el caller hace fallback).
	"""
	import torch

	try:
		from transformers import BitsAndBytesConfig

		qc = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
		pipe = cls.from_pretrained(hf_id, quantization_config=qc, torch_dtype=torch.bfloat16)
		pipe.enable_model_cpu_offload()
		return pipe
	except Exception as e:  # noqa: BLE001
		print(f"  [quant] BitsAndBytesConfig no aplica ({e})", flush=True)

	try:
		from diffusers import PipelineQuantizationConfig

		qc = PipelineQuantizationConfig(
			quant_backend="bitsandbytes_4bit",
			quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": torch.bfloat16},
		)
		pipe = cls.from_pretrained(hf_id, quantization_config=qc, torch_dtype=torch.bfloat16)
		pipe.enable_model_cpu_offload()
		return pipe
	except Exception as e:  # noqa: BLE001
		print(f"  [quant] PipelineQuantizationConfig no aplica ({e})", flush=True)

	return None


def _load(model_id: str):
	cfg = MODELS[model_id]
	import torch

	if cfg["backend"] == "diffusers":
		cls = _diffusers_pipe_class(cfg["pipeline"])
		# 8 GB (7.53 GiB útiles): bf16 no cabe para 4B/6B → 4-bit NF4 (bitsandbytes).
		# IMG_DIFFUSERS_QUANT: bnb4 (def) | seqoff (bf16 + offload secuencial) | bf16
		quant = os.environ.get("IMG_DIFFUSERS_QUANT", "bnb4")
		if quant == "bnb4":
			pipe = _load_diffusers_4bit(cls, cfg["hf_id"])
			if pipe is not None:
				return "diffusers", pipe
			print("  [quant] bnb4 no disponible → fallback bf16 + offload secuencial (más lento)", flush=True)
		pipe = cls.from_pretrained(cfg["hf_id"], torch_dtype=torch.bfloat16)
		if quant == "bf16":
			pipe.to("cuda")
		else:
			pipe.enable_sequential_cpu_offload()
		return "diffusers", pipe

	if cfg["backend"] == "bonsai":
		return "bonsai", _load_bonsai(cfg)

	if cfg["backend"] == "sd_cpp":
		return "sd_cpp", _resolve_sd_cpp(cfg)

	raise RuntimeError(f"backend desconocido: {cfg['backend']}")


def _read_json(path: Path):
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except Exception:
		return {}


def _find_dir(root: Path, pred) -> Path | None:
	for p in sorted(root.rglob("*")):
		if p.is_dir() and pred(p):
			return p
	return None


def _load_bonsai(cfg: dict):
	forge = _forge_home()
	studio = forge / "image-studio"
	if not (studio / "backend_gpu").is_dir():
		raise RuntimeError(f"image-studio/backend_gpu no encontrado en {studio} — corre scripts/imagegen/bootstrap.sh")
	sys.path.insert(0, str(studio))

	from huggingface_hub import snapshot_download

	snap = Path(snapshot_download(cfg["hf_id"], allow_patterns=None))

	def _is_transformer(d: Path) -> bool:
		return (d / "quantization_config.json").is_file() and ((d / "state_dict.pt").is_file() or any(d.glob("*.pt")))

	def _is_vae(d: Path) -> bool:
		cfg_j = d / "config.json"
		return cfg_j.is_file() and "AutoencoderKLFlux2" in str(_read_json(cfg_j).get("_class_name", ""))

	def _is_tokenizer(d: Path) -> bool:
		return (d / "tokenizer_config.json").is_file()

	def _is_text_encoder(d: Path) -> bool:
		if not (d / "config.json").is_file():
			return False
		if any(d.glob("qmodel*")) or (d / "quantization_config.json").is_file():
			arch = str(_read_json(d / "config.json").get("architectures", ""))
			return "Mistral" in arch or "Qwen" in arch  # discriminante (excluye el transformer Flux2)
		return False

	def _resolve(env_key: str, detector) -> Path:
		override = os.environ.get(env_key)
		if override:
			return Path(override)
		found = _find_dir(snap, detector)
		if found is None:
			raise RuntimeError(f"no localicé {env_key} en el snapshot {snap} (override por env si el layout difiere)")
		return found

	transformer = _resolve("BONSAI_TERNARY_TRANSFORMER_PATH", _is_transformer)
	text_encoder = _resolve("BONSAI_TEXT_ENCODER_PATH", _is_text_encoder)
	vae = _resolve("BONSAI_VAE_PATH", _is_vae)
	tokenizer = _resolve("BONSAI_TOKENIZER_PATH", _is_tokenizer)

	from backend_gpu import pipeline_gpu
	from compat_image_studio import apply as _apply_compat

	_apply_compat(pipeline_gpu)  # torch>=2.10: mueve Params con nn.Module.to
	from backend_gpu.pipeline_gpu import GpuPipeline

	pipe = GpuPipeline(
		backend=cfg["backend_name"],
		binary_transformer_path=transformer,  # ctor exige ambos; sólo usamos ternary
		ternary_transformer_path=transformer,
		text_encoder_path=text_encoder,
		vae_path=vae,
		tokenizer_path=str(tokenizer),
	)
	pipe.prewarm()
	return pipe


# ── Generación ──────────────────────────────────────────────────────────────
def _generate(kind: str, pipe, model_id: str, prompt: str, seed: int, size: int):
	import torch
	from PIL import Image

	cfg = MODELS[model_id]
	if kind == "sd_cpp":
		return _sd_cpp_generate(pipe, prompt, seed, size, size)

	if kind == "diffusers":
		gen = torch.Generator(device="cuda").manual_seed(seed)
		img = pipe(
			prompt=prompt,
			height=size,
			width=size,
			num_inference_steps=cfg["steps"],
			guidance_scale=cfg["guidance"],
			generator=gen,
		).images[0]
		return img

	# bonsai (backend_gpu): devuelve PNG bytes
	buf = pipe.generate_png(
		prompt=prompt,
		seed=seed,
		steps=cfg["steps"],
		height=size,
		width=size,
		guidance=cfg["guidance"],
	)
	return Image.open(io.BytesIO(buf))


def _run_model(model_id: str, genres: list, seeds: list, size: int, out_dir: Path) -> int:
	import torch

	out_dir.mkdir(parents=True, exist_ok=True)
	metrics = out_dir / "metrics.jsonl"
	cfg = MODELS[model_id]

	print(f"##### {model_id} ({cfg['backend']}) — {len(genres)} géneros × {len(seeds)} seeds @ {size}² #####", flush=True)
	t_load0 = time.perf_counter()
	try:
		kind, pipe = _load(model_id)
	except Exception as e:  # noqa: BLE001 — carga fallida = elemento no viable
		print(f"  [load] FALLO: {e}", flush=True)
		with metrics.open("a", encoding="utf-8") as f:
			f.write(json.dumps({"model": model_id, "phase": "load", "error": str(e)}, ensure_ascii=False) + "\n")
		return 1
	load_s = time.perf_counter() - t_load0
	print(f"  load {load_s:.1f}s", flush=True)

	n_ok = 0
	n_skip = 0
	for genre in genres:
		gid = genre["id"]
		for seed in seeds:
			png = out_dir / f"{model_id}__{gid}__s{seed}.png"
			if png.exists():
				print(f"  [skip] {png.name}", flush=True)
				n_skip += 1
				continue
			try:
				torch.cuda.reset_peak_memory_stats()
				t0 = time.perf_counter()
				img = _generate(kind, pipe, model_id, genre["prompt"], seed, size)
				wall = time.perf_counter() - t0
				peak = torch.cuda.max_memory_allocated() / (1024**2)
				reserved = torch.cuda.max_memory_reserved() / (1024**2)
				img.save(png)
				rec = {
					"model": model_id,
					"genre": gid,
					"seed": seed,
					"size": size,
					"load_s": round(load_s, 2),
					"wall_s": round(wall, 2),
					"peak_mb": round(peak, 1),
					"reserved_mb": round(reserved, 1),
					"png": png.name,
				}
				with metrics.open("a", encoding="utf-8") as f:
					f.write(json.dumps(rec, ensure_ascii=False) + "\n")
				n_ok += 1
				print(f"  [{gid} s{seed}] {wall:.1f}s  peak {peak:.0f}MB", flush=True)
			except Exception as e:  # noqa: BLE001 — fail-soft a nivel de género
				print(f"  [{gid} s{seed}] FALLO: {e}", flush=True)
				with metrics.open("a", encoding="utf-8") as f:
					f.write(json.dumps({"model": model_id, "genre": gid, "seed": seed, "error": str(e)}, ensure_ascii=False) + "\n")
	# Elemento viable si algo salió o ya existía (resume); si NADA (p.ej. OOM de 8 GB), falla.
	return 0 if (n_ok + n_skip) > 0 else 1


# ── CLI ─────────────────────────────────────────────────────────────────────
def main() -> int:
	ap = argparse.ArgumentParser(description="Banco A/B de generación de imagen local")
	ap.add_argument("--list-models", action="store_true", help="imprime el array JSON de elementos (para element_job)")
	ap.add_argument("--element", action="store_true", help="ejecuta UN elemento leído de RP_ELEMENT (env JSON)")
	ap.add_argument("--models", help="lista csv de ids")
	ap.add_argument("--genres", help="lista csv de ids de género (def: todos)")
	ap.add_argument("--seeds", help="lista csv de seeds (def: los de benchgenres.json)")
	ap.add_argument("--size", type=int, default=0, help="lado en px (def: el de benchgenres.json)")
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
		print("Nada que medir: usa --models o --element")
		return 1
	for m in models:
		if m not in MODELS:
			print(f"modelo desconocido: {m} (válidos: {', '.join(MODELS)})")
			return 1

	genres = bench["genres"]
	if args.genres:
		want = {g.strip() for g in args.genres.split(",") if g.strip()}
		genres = [g for g in genres if g["id"] in want]
	seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else list(bench["seeds"])
	size = args.size or int(bench["size"])
	out_dir = Path(args.out)

	rc = 0
	for model_id in models:
		rc |= _run_model(model_id, genres, seeds, size, out_dir)
	print(f"[out] {out_dir}", flush=True)
	return rc


if __name__ == "__main__":
	sys.exit(main())
