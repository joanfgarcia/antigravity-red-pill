#!/usr/bin/env python3
"""gen_cli.py — lanzador de consola DIRIGIDO POR EL ELENCO (media_profiles.yaml).

Genérico DENTRO DE IMAGEN (`modality: image`): sirve para cualquier modelo de imagen
del elenco (`--model ID`) o cualquier familia/tarea de imagen (`--role TASK`, resuelto
por la cascade `media_roles`). No hardcodea modelos ni backends: los lee del elenco y
delega en el harness (`bench_imagegen` + `gen_image`), que ya despacha por `backend`.
Un modelo que no sea de imagen (p.ej. audio) falla limpio.

Antes de generar, libera la VRAM del LLM residente (los backends GPU la necesitan).

Uso:
	gen_cli.py --model qwen_image_2_1_turbo --prompt "…"
	gen_cli.py --role photoreal --prompt "…" --width 1024 --height 1536 --seed -1
	gen_cli.py --prompt "…"                 # prompt interactivo; --role por defecto
	gen_cli.py --role photoreal --dry-run   # resuelve y muestra sin generar
	gen_cli.py --list-models               # emite el array JSON de modelos de imagen
	gen_cli.py --list-elements --prompt "…" # emite el array JSON de elementos (element_job)

Salida: <out>/<modelo>_<fecha>_s<seed>.png
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _bootstrap_env() -> None:
	"""Defaults canónicos por-máquina. En un job los exporta el runner; para uso de
	consola los resuelve el helper compartido `_config_common` (que lee el `.env` del
	operador y aplica los defaults de forja) — SIN literales de ruta en este script
	(§10.8.1). `setdefault`: nunca pisa lo que ya venga del entorno."""
	sys.path.insert(0, str(HERE.parent))
	from _config_common import media_console_env

	for key, val in media_console_env().items():
		if val:
			os.environ.setdefault(key, val)


_bootstrap_env()

import bench_imagegen as B  # noqa: E402
import gen_image as G  # noqa: E402

DEFAULT_ROLE = "photoreal"

_CONFIG_TEMPLATE = (
	"\n".join(
		[
			"# Plantilla de configuración para `media-gen --config <fichero>`",
			"# Generada por `media-gen --template -`. Los comentarios documentan cada campo.",
			"# Los flags del CLI pisan estos valores si se pasan; si un campo no aparece, se usa el default.",
			"",
			"# ── Modelo ──────────────────────────────────────────────────────────────",
			"# id exacto del elenco (media_profiles.yaml):",
			"model: flux3_klein",
			"# ...o resuelve por familia/tarea de media_roles (p.ej. photoreal, portrait, typography):",
			"# role: photoreal",
			"",
			"# ── Tamaño y semilla ────────────────────────────────────────────────────",
			"# El router ajusta al múltiplo del modelo (dim_multiple). seed: -1 no está soportado (usa un nº).",
			"width: 1024",
			"height: 1024",
			"seed: 42",
			"",
			"# ── Effort (override del sampler del elenco; opcional) ──────────────────",
			"# steps: 8          # nº de pasos (más = mejor/más lento)",
			"# guidance: 1.0     # CFG/guidance",
			"",
			"# ── Prompt (bloque literal; entrécomíllalo tal cual) ────────────────────",
			"prompt: |",
			"  Un retrato editorial de un pescador anciano, piel curtida con arrugas,",
			"  luz de ventana suave, 85mm, fotorrealista, muy detallado.",
			"",
			"# ── Composición (condicionamiento por imagen; opcional) ─────────────────",
			"# Vocabulario canónico; lo NO soportado por el modelo se ignora con aviso (soft-fail).",
			"# composition:",
			"#   reference_image: /ruta/ref.png      # o lista: [a.png, b.png] (multi-referencia)",
			"#   img2img: /ruta/base.png             # edición (re-difusión parcial)",
			"#   mask: /ruta/mask.png                # inpainting (acompaña a img2img)",
			"#   strength: 0.6                       # fuerza de re-difusión",
			'#   negative_prompt: "borroso, texto ilegible"',
			"",
			"# ── Ejecución / salida ──────────────────────────────────────────────────",
			"# out: ~/tmp/red-pill/media/staging/mi-encargo   # dir de salida (def: staging del puesto)",
			"# no_unload: false    # true = no liberar la VRAM del LLM residente antes de generar",
			"# dry_run: false      # true = resolver y mostrar, sin generar",
			"",
			"# ── LOTE (opcional): varias imágenes con el modelo cargado UNA vez ──────",
			"# Si existe `requests:`, se entra en modo lote. Cada petición puede variar",
			"# prompt/seed/tamaño/steps/guidance/composición. Precedencia de cada campo:",
			"#   defaults de máquina  <  este fichero (general)  <  cada `request`  <  flags del CLI",
			"# Se agrupa por modelo y se carga una sola vez por modelo distinto.",
			"# requests:",
			'#   - prompt: "Un retrato fotorrealista…"',
			"#     seed: 42",
			'#   - prompt: "Póster tipográfico de Lisboa…"   # mismo modelo → NO se recarga',
			"#     seed: 7",
			"#     steps: 16",
			"#   - model: zimage_turbo                       # cambia de modelo → carga otra vez",
			'#     prompt: "…"',
		]
	)
	+ "\n"
)


def _profiles() -> dict:
	import yaml

	path = B._media_profiles_path()
	return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_model(data: dict, model: str | None, role: str | None) -> str:
	profiles = data.get("media_profiles") or {}
	if model:
		if model not in profiles:
			raise SystemExit(f"[error] modelo '{model}' no está en el elenco ({B._media_profiles_path()})")
		return model
	role = role or DEFAULT_ROLE
	cascade = (data.get("media_roles") or {}).get(role) or []
	for mid in cascade:
		if mid in profiles and role not in (profiles[mid].get("not_capable_for") or []):
			return mid
	raise SystemExit(f"[error] rol '{role}' sin modelos utilizables en media_roles")


def _ensure_image(model: str) -> str:
	"""El launcher SÓLO genera imagen: un modelo de audio del elenco falla limpio."""
	if model not in B.MODELS:
		raise SystemExit(f"[error] modelo '{model}' no es de imagen (el launcher sólo genera imagen)")
	return model


def _snap(v: int, mult: int) -> int:
	return max(mult, round(v / mult) * mult) if mult > 1 else v


def _composition_from_args(args) -> dict:
	"""Bloque `composition` (vocabulario canónico del elenco) a partir de los flags del CLI."""
	meta: dict = {}
	if args.ref_images:
		meta["reference_image"] = args.ref_images[0] if len(args.ref_images) == 1 else list(args.ref_images)
	if getattr(args, "image", None):
		meta["img2img"] = args.image
	if getattr(args, "mask", None):
		meta["mask"] = args.mask
	if getattr(args, "strength", None) is not None:
		meta["strength"] = args.strength
	if getattr(args, "negative_prompt", None):
		meta["negative_prompt"] = args.negative_prompt
	return meta


_CONFIG_KEYS = frozenset(
	{
		"model",
		"role",
		"width",
		"height",
		"seed",
		"out",
		"prompt",
		"text",
		"image",
		"mask",
		"ref_image",
		"ref_images",
		"strength",
		"negative_prompt",
		"steps",
		"guidance",
		"no_unload",
		"dry_run",
	}
)


def _load_config_file(path: str) -> dict:
	"""Carga un fichero de configuración del encargo: **YAML** (`.yaml`/`.yml`, def) o TOML (`.toml`)."""
	p = Path(path).expanduser()
	if not p.is_file():
		raise SystemExit(f"[error] --config no existe: {p}")
	text = p.read_text(encoding="utf-8")
	if p.suffix.lower() == ".toml":
		import tomllib

		return tomllib.loads(text) or {}
	import yaml

	return yaml.safe_load(text) or {}


def _config_to_defaults(cfg: dict) -> dict:
	"""Traduce el fichero de config a valores por defecto de los flags (el CLI, si se pasa, manda).

	Acepta la forma plana (mismas claves que los flags: `width`, `prompt`, `ref_image`…) y, además, un bloque
	`composition:` con el vocabulario canónico, que se mapea a los flags de composición.
	"""
	cfg = dict(cfg or {})
	comp = cfg.pop("composition", None) or {}
	if isinstance(comp, dict):
		if "reference_image" in comp and not ({"ref_image", "ref_images"} & set(cfg)):
			cfg["ref_images"] = comp["reference_image"] if isinstance(comp["reference_image"], list) else [comp["reference_image"]]
		if "img2img" in comp and "image" not in cfg:
			cfg["image"] = comp["img2img"]
		if "mask" in comp and "mask" not in cfg:
			cfg["mask"] = comp["mask"]
		if "strength" in comp and "strength" not in cfg:
			cfg["strength"] = comp["strength"]
		if "negative_prompt" in comp and "negative_prompt" not in cfg:
			cfg["negative_prompt"] = comp["negative_prompt"]
	return {k: v for k, v in cfg.items() if k in _CONFIG_KEYS}


def _default_out() -> str:
	"""Destino por defecto: el STAGING (CONVENTIONS §7) — resuelto por `_config_common` (fuente única)."""
	from _config_common import console_out_dir

	return console_out_dir()


def _unload_vram(base_url: str) -> None:
	try:
		req = urllib.request.Request(f"{base_url.rstrip('/')}/v1/unload", method="POST")
		with urllib.request.urlopen(req, timeout=5) as resp:
			if resp.status == 200:
				print("[gen] VRAM del LLM residente liberada.", file=sys.stderr)
				time.sleep(2.0)
	except Exception as e:  # noqa: BLE001 — no romper si el daemon no está
		print(f"[gen] aviso: no se pudo pedir el unload ({e})", file=sys.stderr)


def _model_available(prof: dict) -> tuple:
	"""¿Está el modelo EN EL SISTEMA? Delega en la disponibilidad del backend (harness).

	El CLI NO descarga: si el modelo no está, devuelve (False, motivo) y el llamador
	falla limpio. La política por-backend vive en `bench_imagegen` (A42)."""
	return B.backend_available(prof)


def _env_defaults() -> dict:
	"""Defaults de la máquina (nivel más bajo de precedencia)."""
	return {"width": int(os.environ.get("W", 1024)), "height": int(os.environ.get("H", 1024)), "seed": int(os.environ.get("SEED", 42))}


# flag del CLI -> clave de petición (para detectar overrides explícitos por `argv`).
_FLAG_KEYS = {
	"--model": "model",
	"--role": "role",
	"--width": "width",
	"--height": "height",
	"--seed": "seed",
	"--steps": "steps",
	"--guidance": "guidance",
	"--prompt": "prompt",
	"--image": "image",
	"--mask": "mask",
	"--ref-image": "ref_images",
	"--strength": "strength",
	"--negative-prompt": "negative_prompt",
	"--out": "out",
}


def _cli_overrides(args) -> dict:
	"""Campos realmente pasados por el CLI (nivel más alto): se detectan por presencia en `argv`."""
	argv = sys.argv[1:]
	o: dict = {}
	for flag, key in _FLAG_KEYS.items():
		if flag in argv:
			o[key] = getattr(args, key)
	if not o.get("prompt") and (args.prompt or args.text):
		o["prompt"] = args.prompt or args.text
	return o


def _merge_request(general: dict, req: dict, explicit: dict) -> dict:
	"""Precedencia: env-defaults < config(general) < request < flags del CLI."""
	d = dict(_env_defaults())
	d.update(general or {})
	d.update(_config_to_defaults(req or {}))
	d.update(explicit or {})
	return d


def _run_batch(args, config: dict, requests: list) -> int:
	"""Modo lote: `config` trae general + `requests`. Carga el modelo UNA vez por modelo distinto."""
	general = _config_to_defaults(config)
	explicit = _cli_overrides(args)
	data = _profiles()

	B._setup_caches()
	os.environ["HF_HUB_OFFLINE"] = "1"
	os.environ["TRANSFORMERS_OFFLINE"] = "1"

	out_base = Path(args.out or general.get("out") or _default_out())
	out_base.mkdir(parents=True, exist_ok=True)
	if not args.no_unload and not args.dry_run:
		_unload_vram(os.environ.get("DUAL_BIND_PROXY_URL") or "http://127.0.0.1:8760")

	policy = os.environ.get("RP_MEDIA_COMPOSITION_POLICY", "compatible")
	loaded_model = None
	kind = pipe = None
	n_img = n_load = 0
	for i, req in enumerate(requests):
		flat = _merge_request(general, req, explicit)
		model = _ensure_image(_resolve_model(data, flat.get("model"), flat.get("role")))
		prof = (data.get("media_profiles") or {}).get(model) or {}
		mult = int((prof.get("constraints") or {}).get("dim_multiple") or 1)
		w, h = _snap(int(flat["width"]), mult), _snap(int(flat["height"]), mult)
		cons = prof.get("constraints") or {}
		if cons.get("max_pixels") and w * h > int(cons["max_pixels"]):
			raise SystemExit(f"[error] {model}: {w}x{h} excede max_pixels={cons['max_pixels']} (petición #{i})")
		prompt = flat.get("prompt")
		if not prompt:
			raise SystemExit(f"[error] petición #{i}: falta prompt")
		ns = argparse.Namespace(
			prompt=prompt,
			seed=int(flat["seed"]),
			steps=flat.get("steps"),
			guidance=flat.get("guidance"),
			image=flat.get("image"),
			mask=flat.get("mask"),
			ref_images=flat.get("ref_images"),
			strength=flat.get("strength"),
			negative_prompt=flat.get("negative_prompt"),
		)
		meta = _composition_from_args(ns)
		if meta:
			meta, warns = B.apply_composition(meta, {**prof, "id": model})
			for warn in warns:
				print(f"[gen] aviso: {warn} (política {policy})", file=sys.stderr)
		if args.dry_run:
			print(f"[dry-run] #{i} {model} {w}x{h} s{flat['seed']} steps={flat.get('steps')} «{prompt[:50]}»", file=sys.stderr)
			continue
		ok, why = _model_available(prof)
		if not ok:
			raise SystemExit(f"[error] modelo '{model}' no disponible ({why})")
		if model != loaded_model:
			kind, pipe = B._load(model)
			loaded_model = model
			n_load += 1
		try:
			img = G._gen(kind, pipe, model, prompt, int(flat["seed"]), w, h, meta, steps=flat.get("steps"), guidance=flat.get("guidance"))
		except RuntimeError as e:  # noqa: BLE001
			raise SystemExit(f"[error] petición #{i} falló: {str(e)[:300]}") from e
		out = out_base / f"{model}_{time.strftime('%Y%m%d-%H%M%S')}_s{flat['seed']}_{i:02d}.png"
		img.save(out)
		n_img += 1
		print(f"[ok] {out}")
	print(f"[batch] {n_img} imagen(es), {n_load} carga(s) de modelo (peticiones={len(requests)})")
	return 0


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--model", help="id exacto del elenco")
	ap.add_argument("--role", help=f"familia/tarea de media_roles (def: {DEFAULT_ROLE})")
	ap.add_argument("--prompt", help="prompt (si falta, se pide por consola)")
	ap.add_argument("text", nargs="?", help="prompt posicional (alternativa a --prompt)")
	ap.add_argument(
		"--width", type=int, default=int(os.environ.get("W", 1024)), help="ancho en px (def: $W o 1024; se ajusta al múltiplo del modelo)"
	)
	ap.add_argument(
		"--height", type=int, default=int(os.environ.get("H", 1024)), help="alto en px (def: $H o 1024; se ajusta al múltiplo del modelo)"
	)
	ap.add_argument("--seed", type=int, default=int(os.environ.get("SEED", 42)), help="semilla (def: $SEED o 42)")
	ap.add_argument("--steps", type=int, default=None, help="nº de pasos de inferencia (override del elenco; más pasos = mejor/más lento)")
	ap.add_argument("--guidance", type=float, default=None, help="guidance/CFG (override del elenco)")
	ap.add_argument("--out", default=None, help="dir de salida (def: staging — $OUTDIR/$RP_MEDIA_STAGING/cli)")
	ap.add_argument("--image", help="imagen de entrada para EDITAR (backend sd_cpp)")
	ap.add_argument("--mask", help="máscara de inpainting (acompaña a --image)")
	ap.add_argument("--ref-image", action="append", dest="ref_images", help="imagen de referencia (repetible; composición)")
	ap.add_argument("--strength", type=float, help="fuerza de re-difusión en edición (def: del elenco / 0.75)")
	ap.add_argument("--negative-prompt", dest="negative_prompt", help="prompt negativo (si el modelo lo soporta)")
	ap.add_argument("--no-unload", action="store_true", help="no pedir el unload del LLM residente")
	ap.add_argument("--dry-run", action="store_true", help="resolver y mostrar, sin generar")
	ap.add_argument("--list-models", action="store_true", help="emite el array JSON de modelos de imagen (elenco)")
	ap.add_argument("--list-elements", action="store_true", help="emite el array JSON de elementos (para element_job)")
	ap.add_argument("--config", help="fichero YAML/TOML con toda la configuración (model, tamaño, seed, prompt, composición…)")
	ap.add_argument("--template", metavar="FICHERO", help="escribe una plantilla YAML comentada de --config (usa '-' para stdout) y sale")
	# Fichero de config primero (como defaults); los flags del CLI, si se pasan, mandan.
	_pre, _ = ap.parse_known_args()
	_config = _load_config_file(_pre.config) if _pre.config else {}
	if _config:
		ap.set_defaults(**_config_to_defaults(_config))
	args = ap.parse_args()

	if args.template:
		if args.template in ("-", ""):
			print(_CONFIG_TEMPLATE)
		else:
			Path(args.template).expanduser().write_text(_CONFIG_TEMPLATE, encoding="utf-8")
			print(f"[ok] plantilla escrita en {args.template}")
		return 0

	if args.list_models:
		print(json.dumps([{"model": m} for m in B.MODELS], ensure_ascii=False))
		return 0

	if args.list_elements:
		data = _profiles()
		if isinstance(_config.get("requests"), list):
			general = _config_to_defaults(_config)
			explicit = _cli_overrides(args)
			els = []
			for i, req in enumerate(_config["requests"]):
				flat = _merge_request(general, req, explicit)
				model = _ensure_image(_resolve_model(data, flat.get("model"), flat.get("role")))
				prof = (data.get("media_profiles") or {}).get(model) or {}
				mult = int((prof.get("constraints") or {}).get("dim_multiple") or 1)
				w, h = _snap(int(flat["width"]), mult), _snap(int(flat["height"]), mult)
				ns = argparse.Namespace(
					image=flat.get("image"),
					mask=flat.get("mask"),
					ref_images=flat.get("ref_images"),
					strength=flat.get("strength"),
					negative_prompt=flat.get("negative_prompt"),
				)
				el = {
					"model": model,
					"prompt": flat.get("prompt"),
					"seed": int(flat["seed"]),
					"width": w,
					"height": h,
					"out": args.out or general.get("out"),
					"tag": (req or {}).get("tag") or f"req{i:02d}",
				}
				if flat.get("steps") is not None:
					el["steps"] = flat["steps"]
				if flat.get("guidance") is not None:
					el["guidance"] = flat["guidance"]
				comp = _composition_from_args(ns)
				if comp:
					el["composition"] = comp
				els.append(el)
			print(json.dumps(els, ensure_ascii=False))
			return 0
		model = _ensure_image(_resolve_model(data, args.model, args.role))
		prompt = args.prompt or args.text
		if not prompt:
			print("[error] falta prompt (--prompt)", flush=True)
			return 1
		prof = (data.get("media_profiles") or {}).get(model) or {}
		mult = int((prof.get("constraints") or {}).get("dim_multiple") or 1)
		w, h = _snap(args.width, mult), _snap(args.height, mult)
		comp = _composition_from_args(args)
		el = {"model": model, "prompt": prompt, "seed": args.seed, "width": w, "height": h, "out": args.out}
		if comp:
			el["composition"] = comp
		print(json.dumps([el], ensure_ascii=False))
		return 0

	if isinstance(_config.get("requests"), list):
		return _run_batch(args, _config, _config["requests"])

	args.out = args.out or _default_out()

	data = _profiles()
	model = _ensure_image(_resolve_model(data, args.model, args.role))
	prof = (data.get("media_profiles") or {}).get(model) or {}
	mult = int((prof.get("constraints") or {}).get("dim_multiple") or 1)
	w, h = _snap(args.width, mult), _snap(args.height, mult)
	backend = prof.get("backend")

	# Guard de tamaño (espejo de `reject_oversize` del router; el CLI no pasaba por él):
	# fuera de la envolvente de VRAM del modelo → error limpio en vez de OOM de sd-cli.
	cons = prof.get("constraints") or {}
	max_px = cons.get("max_pixels")
	if max_px and w * h > int(max_px):
		raise SystemExit(
			f"[error] {model}: {w}x{h} ({w * h} px) excede max_pixels={max_px} del modelo en este puesto; "
			f"usa ≤{int(int(max_px) ** 0.5)}² (p.ej. 1024x1024)."
		)
	peak = (prof.get("vram_footprint") or {}).get("peak_mb")
	max_vram = cons.get("max_vram_mb")
	if max_vram and peak and float(peak) > float(max_vram):
		raise SystemExit(f"[error] {model}: pico ~{peak} MB excede max_vram_mb={max_vram}")

	B._setup_caches()  # HF_HOME = caché del forge (misma que los jobs)
	# Política del CLI: NO descargar nunca. Trabaja con lo que ya esté en la caché.
	os.environ["HF_HUB_OFFLINE"] = "1"
	os.environ["TRANSFORMERS_OFFLINE"] = "1"

	# El modelo escogido (o el por defecto del rol) DEBE estar en el sistema.
	ok, why = _model_available(prof)
	if not ok:
		raise SystemExit(f"[error] modelo '{model}' no está disponible localmente ({why}). El CLI no descarga: instálalo aparte.")

	print(f"[gen] modelo={model} backend={backend} {w}x{h} seed={args.seed}", file=sys.stderr)
	if args.dry_run:
		return 0

	# El prompt es OBLIGATORIO y en UN solo argumento (entrecomíllalo en el shell).
	prompt = args.prompt or args.text
	if not prompt:
		raise SystemExit('[error] falta el prompt — entrécomíllalo: media-gen --model <ID> "<prompt>"')

	if not args.no_unload:
		_unload_vram(os.environ.get("DUAL_BIND_PROXY_URL") or "http://127.0.0.1:8760")

	kind, pipe = B._load(model)
	# Composición (referencia/edición) unificada: la filtra el harness según lo que declara el elenco. Lo no
	# soportado AVISA (soft-fail, política `compatible`) y se renderiza igual; en `strict`, falla.
	policy = os.environ.get("RP_MEDIA_COMPOSITION_POLICY", "compatible")
	meta = _composition_from_args(args)
	if meta:
		try:
			meta, warns = B.apply_composition(meta, {**prof, "id": model})
		except RuntimeError as e:
			raise SystemExit(f"[error] {e}") from e
		for warn in warns:
			print(f"[gen] aviso: {warn} (política {policy})", file=sys.stderr)
	if meta:
		print(f"[gen] composición: {', '.join(meta)} (política {policy})", file=sys.stderr)
	if args.steps is not None or args.guidance is not None:
		base = B.MODELS[model]
		eff_steps = args.steps if args.steps is not None else base.get("steps")
		eff_guid = args.guidance if args.guidance is not None else base.get("guidance")
		print(f"[gen] effort: steps={eff_steps} guidance={eff_guid}", file=sys.stderr)
	try:
		img = G._gen(kind, pipe, model, prompt, args.seed, w, h, meta, steps=args.steps, guidance=args.guidance)
	except RuntimeError as e:  # noqa: BLE001 — fallo del backend → error limpio, sin traceback
		msg = str(e)
		hint = " (posible VRAM agotada: baja la resolución)" if "memory" in msg.lower() else ""
		raise SystemExit(f"[error] generación falló{hint}: {msg[:300]}") from e

	outdir = Path(args.out)
	outdir.mkdir(parents=True, exist_ok=True)
	out = outdir / f"{model}_{time.strftime('%Y%m%d-%H%M%S')}_s{args.seed}.png"
	img.save(out)
	print(f"[ok] {out}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
