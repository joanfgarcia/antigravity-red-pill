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
# llama.cpp escribe `model buffer size` en `load_tensors`; el patrón viejo
# (`model size`) no casaba y dejaba `model_mb = 0`, inflando la predicción.
MODEL_RE = re.compile(r"model(?: buffer)? size\s*=\s*([0-9.]+)\s*MiB", re.I)
# El modelo se imprime dos veces: el mmap del fichero (CPU) y el buffer en VRAM.
# Lo que resta de presupuesto es el de la GPU.
MODEL_CUDA_RE = re.compile(r"CUDA\d+\s+model buffer size\s*=\s*([0-9.]+)\s*MiB", re.I)


def _mib(pattern: re.Pattern[str], text: str) -> int:
	found = pattern.search(text)
	return int(float(found.group(1))) if found else 0


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
		# Sin `-lv 4` el servidor no imprime los buffers: ni `KV buffer size` ni
		# `model buffer size`. A verbosidad 3 el log sólo dice que escucha, y el
		# sondeo se quedaba sin la magnitud que viene a medir.
		"-lv",
		"4",
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
		if "server is listening" in text or "listening on http" in text:
			kv_mb = _mib(KV_RE, text)
			model_mb = _mib(MODEL_CUDA_RE, text) or _mib(MODEL_RE, text)
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
		if pred <= args.probe_ctx:
			# La sonda ya cargó: es el suelo verificado.
			best = args.probe_ctx
			print(f"{kv:<6} VERIFICADO: carga a {best // 1024}k (la predicción no da para más)")
		else:
			# Descenso simulado de 4k (lo de antes) no alcanza cuando la predicción
			# se pasa: 122k → 118k → 114k sigue lejos de un techo real de 96k y el
			# informe dice "no" habiendo sitio. Bisección entre la sonda (carga) y
			# la predicción (falla): converge en ≤4 arranques a 1k de error.
			lo, hi = args.probe_ctx, pred
			ok2, kv2, _, why2 = boot(model, args.alias, hi, kv)
			if ok2:
				best = hi
				print(f"{kv:<6} VERIFICADO: carga a {hi // 1024}k (KV {kv2} MiB, VRAM total {vram_used_mb()} MiB)")
			else:
				print(f"{kv:<6} {hi // 1024}k no entra ({why2})")
				for _ in range(6):
					mid = ((lo + hi) // 2) // 1024 * 1024
					if mid <= lo or hi - lo <= 1024:
						break
					ok3, kv3, _, why3 = boot(model, args.alias, mid, kv)
					if ok3:
						lo = mid
						print(f"{kv:<6} {mid // 1024}k entra (KV {kv3} MiB, VRAM total {vram_used_mb()} MiB)")
					else:
						hi = mid
						print(f"{kv:<6} {mid // 1024}k no entra ({why3})")
				best = lo
				print(f"{kv:<6} VERIFICADO: techo {best // 1024}k (último que carga)" if best else f"{kv:<6} techo por debajo de la sonda")
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
