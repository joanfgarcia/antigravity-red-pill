#!/usr/bin/env python3
"""gen_cli.py — lanzador de consola DIRIGIDO POR EL ELENCO (media_profiles.yaml).

Genérico: sirve para cualquier modelo del elenco (`--model ID`) o cualquier
familia/tarea (`--role TASK`, resuelto por la cascade `media_roles`). No hardcodea
modelos ni backends: los lee del elenco y delega en el harness
(`bench_imagegen` + `gen_image`), que ya despacha por `backend`.

Antes de generar, libera la VRAM del LLM residente (los backends GPU la necesitan).

Uso:
  gen_cli.py --model qwen_image_2_1_turbo --prompt "…"
  gen_cli.py --role photoreal --prompt "…" --width 1024 --height 1536 --seed -1
  gen_cli.py --prompt "…"                 # prompt interactivo; --role por defecto
  gen_cli.py --role photoreal --dry-run   # resuelve y muestra sin generar

Salida: <out>/<modelo>_<fecha>_s<seed>.png
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _bootstrap_env() -> None:
	"""Defaults canónicos por-máquina. En un job los exporta el runner; aquí, para
	uso de consola. `setdefault`: nunca pisa lo que ya venga del entorno."""
	cfg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
	os.environ.setdefault("REDPILL_MEDIA_PROFILES", str(Path(cfg) / "red-pill" / "media_profiles.yaml"))
	os.environ.setdefault("REDPILL_RUNTIMES", str(Path(cfg) / "red-pill" / "runtimes.yaml"))
	os.environ.setdefault("IMAGE_FORGE_HOME", str(Path.home() / "opt" / "image-forge"))


_bootstrap_env()

import bench_imagegen as B  # noqa: E402
import gen_image as G  # noqa: E402

DEFAULT_ROLE = "photoreal"


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


def _snap(v: int, mult: int) -> int:
	return max(mult, round(v / mult) * mult) if mult > 1 else v


def _unload_vram(base_url: str) -> None:
	try:
		req = urllib.request.Request(f"{base_url.rstrip('/')}/v1/unload", method="POST")
		with urllib.request.urlopen(req, timeout=5) as resp:
			if resp.status == 200:
				print("[gen] VRAM del LLM residente liberada.", file=sys.stderr)
				time.sleep(2.0)
	except Exception as e:  # noqa: BLE001 — no romper si el daemon no está
		print(f"[gen] aviso: no se pudo pedir el unload ({e})", file=sys.stderr)


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--model", help="id exacto del elenco")
	ap.add_argument("--role", help=f"familia/tarea de media_roles (def: {DEFAULT_ROLE})")
	ap.add_argument("--prompt", help="prompt (si falta, se pide por consola)")
	ap.add_argument("text", nargs="?", help="prompt posicional (alternativa a --prompt)")
	ap.add_argument("--width", type=int, default=int(os.environ.get("W", 1024)))
	ap.add_argument("--height", type=int, default=int(os.environ.get("H", 1024)))
	ap.add_argument("--seed", type=int, default=int(os.environ.get("SEED", 42)))
	ap.add_argument("--out", default=os.environ.get("OUTDIR") or str(Path.cwd() / "out"))
	ap.add_argument("--no-unload", action="store_true", help="no pedir el unload del LLM residente")
	ap.add_argument("--dry-run", action="store_true", help="resolver y mostrar, sin generar")
	args = ap.parse_args()

	data = _profiles()
	model = _resolve_model(data, args.model, args.role)
	prof = (data.get("media_profiles") or {}).get(model) or {}
	mult = int((prof.get("constraints") or {}).get("dim_multiple") or 1)
	w, h = _snap(args.width, mult), _snap(args.height, mult)
	backend = prof.get("backend")

	print(f"[gen] modelo={model} backend={backend} {w}x{h} seed={args.seed}", file=sys.stderr)
	if args.dry_run:
		return 0

	prompt = args.prompt or args.text
	if not prompt:
		if sys.stdin.isatty():
			prompt = input("Prompt: ")
		if not prompt:
			raise SystemExit("[error] prompt vacío")

	if not args.no_unload:
		_unload_vram(os.environ.get("DUAL_BIND_PROXY_URL") or "http://127.0.0.1:8760")

	kind, pipe = B._load(model)
	img = G._gen(kind, pipe, model, prompt, args.seed, w, h)

	outdir = Path(args.out)
	outdir.mkdir(parents=True, exist_ok=True)
	out = outdir / f"{model}_{time.strftime('%Y%m%d-%H%M%S')}_s{args.seed}.png"
	img.save(out)
	print(f"[ok] {out}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
