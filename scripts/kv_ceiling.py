"""Techo de contexto real: ¿cuánta ventana cabe según la cuantización del KV?

Para cada tipo de KV (`f16`, `q8_0`, `q4_0`) se mide el coste del cache por 1k
tokens a una ventana de sonda, se calcula la ventana máxima que cabe en la VRAM
disponible y se **verifica** arrancando el servidor a esa ventana (si no cabe,
baja hasta que arranque). No se fía de la cuenta: el número que se reporta es el
que el servidor aceptó de verdad.

Uso:
	python scripts/kv_ceiling.py --model ~/.local/share/red-pill/models/MiMo...gguf \
		--alias mimo --kv q8_0,q4_0 --probe-ctx 16384 --budget-mb 7500
"""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from pathlib import Path

IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda"
NAME = "dokime-kvprobe"
KV_RE = re.compile(r"KV buffer size\s*=\s*([0-9.]+)\s*MiB", re.I)
MODEL_RE = re.compile(r"model size\s*=\s*([0-9.]+)\s*MiB", re.I)


def vram_used_mb() -> int:
	out = subprocess.run(
		["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
		capture_output=True,
		text=True,
		check=False,
	)
	try:
		return int(float(out.stdout.strip().splitlines()[0]))
	except Exception:
		return -1


def stop() -> None:
	subprocess.run(["podman", "rm", "-f", NAME], capture_output=True, text=True, check=False)


def boot(model: Path, alias: str, ctx: int, kv: str, timeout: int = 180) -> tuple[bool, int, int, str]:
	"""Arranca el servidor y devuelve (cargó, kv_mb, modelo_mb, motivo)."""
	stop()
	cmd = [
		"podman",
		"run",
		"-d",
		"--name",
		NAME,
		"--device",
		"nvidia.com/gpu=all",
		"-v",
		f"{model}:/models/model.gguf:ro",
		IMAGE,
		"-m",
		"/models/model.gguf",
		"--alias",
		alias,
		"--host",
		"0.0.0.0",
		"--port",
		"8081",
		"-c",
		str(ctx),
		"-ctk",
		kv,
		"-ctv",
		kv,
		"-fa",
		"on",
		"-ngl",
		"99",
		"-np",
		"1",
		"--jinja",
	]
	run = subprocess.run(cmd, capture_output=True, text=True, check=False)
	if run.returncode != 0:
		return False, 0, 0, (run.stderr or run.stdout).strip()[:200]

	t0 = time.time()
	while time.time() - t0 < timeout:
		time.sleep(2)
		state = subprocess.run(["podman", "inspect", "-f", "{{.State.Running}}", NAME], capture_output=True, text=True, check=False)
		if (state.stdout or "").strip() != "true":
			break
		logs = subprocess.run(["podman", "logs", NAME], capture_output=True, text=True, check=False)
		text = (logs.stdout or "") + (logs.stderr or "")
		if "server is listening" in text:
			kv_mb = int(float(KV_RE.search(text).group(1))) if KV_RE.search(text) else 0
			model_mb = int(float(MODEL_RE.search(text).group(1))) if MODEL_RE.search(text) else 0
			return True, kv_mb, model_mb, ""
		if "failed to allocate" in text or "error loading model" in text:
			return False, 0, 0, "sin VRAM"

	logs = subprocess.run(["podman", "logs", NAME], capture_output=True, text=True, check=False)
	text = ((logs.stdout or "") + (logs.stderr or "")).strip().splitlines()
	return False, 0, 0, (text[-1] if text else "timeout")[:200]


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--model", required=True)
	ap.add_argument("--alias", default="probe")
	ap.add_argument("--kv", default="q8_0,q4_0")
	ap.add_argument("--probe-ctx", type=int, default=16384)
	ap.add_argument("--budget-mb", type=int, default=7500)
	args = ap.parse_args()

	model = Path(args.model).expanduser()
	print(f"modelo: {model.name} ({model.stat().st_size / 1024**3:.2f} GB)")
	print(f"presupuesto VRAM: {args.budget_mb} MiB · sonda {args.probe_ctx} tokens\n")

	rows = []
	for kv in [x.strip() for x in args.kv.split(",") if x.strip()]:
		ok, kv_mb, model_mb, why = boot(model, args.alias, args.probe_ctx, kv)
		if not ok:
			print(f"{kv:<6} sonda {args.probe_ctx}: NO CARGA ({why})")
			rows.append({"kv": kv, "ctx": 0, "kv_mb": 0, "verdict": f"no carga: {why}"})
			continue
		per_1k = kv_mb / (args.probe_ctx / 1000)
		room = max(0, args.budget_mb - model_mb - 400)  # 400 MiB de compute buffer
		pred = int(room / per_1k * 1000) // 1024 * 1024
		print(f"{kv:<6} sonda: KV {kv_mb} MiB a {args.probe_ctx} → {per_1k:.1f} MiB/1k · modelo {model_mb} MiB")
		print(f"{kv:<6} predicho: {pred // 1024}k tokens (margen {room} MiB)")

		best = 0
		for attempt in (pred, pred - 4096, pred - 8192):
			if attempt <= 0:
				continue
			ok2, kv2, _, why2 = boot(model, args.alias, attempt, kv)
			if ok2:
				best = attempt
				used = vram_used_mb()
				print(f"{kv:<6} VERIFICADO: carga a {attempt // 1024}k (KV {kv2} MiB, VRAM total {used} MiB)")
				break
			print(f"{kv:<6} {attempt // 1024}k no entra ({why2})")
		rows.append({"kv": kv, "ctx": best, "kv_mb": kv_mb, "per_1k": round(per_1k, 1), "verdict": "ok" if best else "no"})

	stop()
	print("\n── resumen ──")
	for r in rows:
		if r["verdict"] == "ok":
			print(f"  {r['kv']:<6} {r['ctx'] // 1024:>4}k tokens · {r['per_1k']} MiB/1k")
		else:
			print(f"  {r['kv']:<6} {r['verdict']}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
