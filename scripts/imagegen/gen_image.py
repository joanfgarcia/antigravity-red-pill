#!/usr/bin/env python3
"""gen_image.py — generación de imagen local con PROMPT LIBRE.

Hermano de `bench_imagegen.py` (que recorre la matriz fija de géneros). Este
reutiliza su registro MODELS y su carga (`_load`) pero acepta un prompt a medida,
tamaño no-cuadrado (p.ej. pantalla de carga 16:9) y salida incremental idempotente.

TODO entra por parámetro (el código es estable): prompt, tamaño, ruta, nombre,
seed, modelos y snap. No se edita el código para cambiar el contenido.

		python gen_image.py --models flux2_klein --prompt "a cat" \
				--width 1920 --height 1080 --out /ruta --name mi_imagen --seed 42 --snap 8

Como `element_job` (un elemento por modelo):
		python gen_image.py --list-elements --prompt "..." --out D --width W --height H
		python gen_image.py --element            # lee RP_ELEMENT (JSON)

RP_ELEMENT: {model, prompt, seed, width, height, out, tag?, name?}
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _bench():
	spec = importlib.util.spec_from_file_location("bench_imagegen", HERE / "bench_imagegen.py")
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


BENCH = _bench()
MODELS = BENCH.MODELS

# El ajuste de múltiplos por modelo lo resuelve el ROUTER (docs/CORE/MEDIA_MODELS.md) en
# el lado red-pill y llega por env RP_MEDIA_WIDTH/HEIGHT ya adaptado. Aquí queda un
# `--snap`/`RP_IMAGE_SNAP` OPCIONAL (default 1 = sin ajuste) para uso standalone.
SNAP = int(os.environ.get("RP_IMAGE_SNAP", "1"))


def _snap(v: int) -> int:
	return max(SNAP, round(v / SNAP) * SNAP) if SNAP > 1 else v


def _safe_stem(value: str, what: str) -> str:
	"""Rechaza nombres que escapan del dir de salida (path traversal / separadores)."""
	v = (value or "").strip()
	if not v or Path(v).is_absolute() or "/" in v or "\\" in v or ".." in Path(v).parts or v.startswith("."):
		raise ValueError(f"{what} inválido (sin separadores ni '..'): {value!r}")
	return v


def _console_out() -> Path:
	sys.path.insert(0, str(HERE.parent))
	from _config_common import console_out_dir

	return Path(console_out_dir())


def _default_out() -> Path:
	"""Destino por defecto: el STAGING (CONVENTIONS §7) — resuelto por `_config_common` (fuente única)."""
	return _console_out()


def _element_out(el: dict, args_out: str | None) -> str:
	"""Modo `--element`: TODO el payload es no confiable (el `out` del elemento Y el
	`--out` del step_command) → confinado al staging."""
	return str(_confine_out(Path(el.get("out") or args_out or _default_out())))


def _confine_out(path: Path) -> Path:
	"""Confina el `out` que llega del payload (RP_ELEMENT, CONVENTIONS §7): no debe escapar del
	staging. `$OUTDIR` (override explícito del operador) exime. La raíz NO se toma de una
	fuente que el payload pueda ensanchar (el driver filtra `RP_MEDIA_STAGING`/`OUTDIR`)."""
	if os.environ.get("OUTDIR"):
		return Path(path)
	root = _console_out().parent
	if root.resolve() == Path(root.anchor):  # raíz '/' → staging inválido
		raise SystemExit(f"[error] staging inválido (raíz de disco): {root}")
	resolved = Path(path).expanduser().resolve()
	if not resolved.is_relative_to(root.expanduser().resolve()):
		raise SystemExit(f"[error] 'out' fuera del staging: {resolved} ∉ {root} (§7)")
	return resolved


def _gen(kind: str, pipe, model_id: str, prompt: str, seed: int, width: int, height: int, meta: dict = None):
	"""Delega en el registro ÚNICO del harness (`bench_imagegen.generate`, AD-052)."""
	return BENCH.generate(kind, MODELS[model_id], pipe, prompt, seed, width, height, meta)


def _run_element(el: dict) -> int:
	media_error = os.environ.get("RP_MEDIA_ERROR")
	if media_error:
		print(f"[media] petición imposible (router): {media_error}", flush=True)
		return 1

	import torch

	model_id = str(el.get("model") or "")
	if model_id not in MODELS:
		print(f"modelo desconocido: {model_id!r} (válidos: {', '.join(MODELS)})", flush=True)
		return 1
	prompt = str(el.get("prompt") or "")
	if not prompt:
		print("prompt vacío", flush=True)
		return 1
	seed = int(el.get("seed") or 42)
	width = _snap(int(os.environ.get("RP_MEDIA_WIDTH") or el.get("width") or 1024))
	height = _snap(int(os.environ.get("RP_MEDIA_HEIGHT") or el.get("height") or 1024))
	out_dir = Path(el.get("out") or _default_out())
	out_dir.mkdir(parents=True, exist_ok=True)
	metrics = out_dir / "metrics.jsonl"

	# Nombre: `--name` exacto si viene; si no, patrón <modelo>__<tag>__s<seed>.
	name = el.get("name")
	tag = str(el.get("tag") or "out")
	stem = _safe_stem(str(name), "name") if name else f"{model_id}__{_safe_stem(tag, 'tag')}__s{seed}"
	png = out_dir / f"{stem}.png"
	if png.is_symlink():
		print(f"[error] destino es un symlink (no permitido): {png}", flush=True)
		return 1
	if png.exists():
		print(f"[skip] {png.name} (ya existe)", flush=True)
		return 0

	t0 = time.perf_counter()
	print(f"##### {model_id} @ {width}x{height} s{seed} #####", flush=True)
	try:
		kind, pipe = BENCH._load(model_id)
	except Exception as e:  # noqa: BLE001
		print(f"  [load] FALLO: {e}", flush=True)
		with metrics.open("a", encoding="utf-8") as f:
			f.write(json.dumps({"model": model_id, "phase": "load", "error": str(e)}, ensure_ascii=False) + "\n")
		return 1
	load_s = time.perf_counter() - t0

	# Composición (condicionamiento por imagen): el elemento manda sobre el env del job (precedencia).
	meta = el.get("composition")
	if meta is None:
		raw = os.environ.get("RP_MEDIA_COMPOSITION")
		if raw:
			try:
				meta = json.loads(raw)
			except Exception:  # noqa: BLE001
				meta = None
	meta = meta or {}

	try:
		torch.cuda.reset_peak_memory_stats()
		t1 = time.perf_counter()
		img = _gen(kind, pipe, model_id, prompt, seed, width, height, meta)
		wall = time.perf_counter() - t1
		peak = torch.cuda.max_memory_allocated() / (1024**2)
		img.save(png)
		rec = {
			"model": model_id,
			"kind": kind,
			"seed": seed,
			"size": f"{width}x{height}",
			"load_s": round(load_s, 2),
			"wall_s": round(wall, 2),
			"peak_mb": round(peak, 1),
			"png": png.name,
		}
		raw_warn = os.environ.get("RP_MEDIA_WARNINGS")
		if raw_warn:
			try:
				rec["warnings"] = list(json.loads(raw_warn))
			except Exception:  # noqa: BLE001
				rec["warnings"] = [raw_warn]
		with metrics.open("a", encoding="utf-8") as f:
			f.write(json.dumps(rec, ensure_ascii=False) + "\n")
		print(f"  [ok] {wall:.1f}s  peak {peak:.0f}MB  → {png.name}", flush=True)
		return 0
	except Exception as e:  # noqa: BLE001
		print(f"  FALLO: {e}", flush=True)
		with metrics.open("a", encoding="utf-8") as f:
			f.write(json.dumps({"model": model_id, "error": str(e)}, ensure_ascii=False) + "\n")
		return 1


def _read_prompt(args) -> str:
	if args.prompt_file:
		return Path(args.prompt_file).read_text(encoding="utf-8").strip()
	return (args.prompt or "").strip()


def main() -> int:
	ap = argparse.ArgumentParser(description="Generación de imagen local con prompt libre")
	ap.add_argument("--list-models", action="store_true")
	ap.add_argument("--list-elements", action="store_true", help="emite el array JSON de elementos (para element_job)")
	ap.add_argument("--element", action="store_true", help="ejecuta UN elemento de RP_ELEMENT")
	ap.add_argument("--models", help="csv de ids (def: todos)")
	ap.add_argument("--prompt")
	ap.add_argument("--prompt-file")
	ap.add_argument("--seed", type=int, default=42)
	ap.add_argument("--width", type=int, default=1024)
	ap.add_argument("--height", type=int, default=1024)
	ap.add_argument("--out", default=None, help="dir de salida (def: staging — $OUTDIR/$RP_MEDIA_STAGING/cli)")
	ap.add_argument("--tag", default="out", help="etiqueta de variante en el nombre del PNG (def: out)")
	ap.add_argument("--name", help="nombre EXACTO del PNG (sin extensión); anula el patrón modelo__tag__seed")
	ap.add_argument("--snap", type=int, default=None, help="múltiplo al que ajustar ancho/alto (def: 1 = sin ajuste; env RP_IMAGE_SNAP)")
	args = ap.parse_args()

	global SNAP
	if args.snap:
		SNAP = args.snap

	if args.list_models:
		print(json.dumps([{"model": m} for m in MODELS], ensure_ascii=False))
		return 0

	if args.list_elements:
		prompt = _read_prompt(args)
		if not prompt:
			print("falta prompt (--prompt o --prompt-file)", flush=True)
			return 1
		ids = [m.strip() for m in (args.models or ",".join(MODELS)).split(",") if m.strip()]
		w, h = _snap(args.width), _snap(args.height)
		comp = None
		raw = os.environ.get("RP_MEDIA_COMPOSITION")
		if raw:
			try:
				comp = json.loads(raw)
			except Exception:  # noqa: BLE001
				comp = None
		els = []
		for m in ids:
			el = {"model": m, "prompt": prompt, "seed": args.seed, "width": w, "height": h, "out": args.out, "tag": args.tag, "name": args.name}
			if comp:
				el["composition"] = comp
			els.append(el)
		print(json.dumps(els, ensure_ascii=False))
		return 0

	BENCH._setup_caches()

	if args.element:
		raw = os.environ.get("RP_ELEMENT") or ""
		try:
			el = json.loads(raw)
		except Exception as e:  # noqa: BLE001
			print(f"RP_ELEMENT inválido ({e}): {raw!r}", flush=True)
			return 1
		el["out"] = _element_out(el, args.out)
		return _run_element(el)

	prompt = _read_prompt(args)
	if not prompt:
		print("falta prompt (--prompt o --prompt-file)", flush=True)
		return 1
	out = args.out or str(_default_out())
	rc = 0
	for m in [x.strip() for x in (args.models or ",".join(MODELS)).split(",") if x.strip()]:
		rc |= _run_element(
			{
				"model": m,
				"prompt": prompt,
				"seed": args.seed,
				"width": args.width,
				"height": args.height,
				"out": out,
				"tag": args.tag,
				"name": args.name,
			}
		)
	return rc


if __name__ == "__main__":
	sys.exit(main())
