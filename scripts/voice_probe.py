#!/usr/bin/env python3
"""voice_probe.py — compara la VOZ de varias familias con la misma identidad.

Misma tarjeta, misma memoria y mismo prompt; lo único que cambia son los pesos. El
alias (`bench`) y la ventana (16k) se mantienen fijos para que la comparación no se
contamine con la configuración. Las respuestas quedan en `--out`.

No juzga: recoge. El juicio («¿cambia el deje?») es de quien lee, y por eso el
resultado son textos, no un score. Requiere el sandbox de Dokimé arriba.
"""

import json
import os
import subprocess
import time
from pathlib import Path

# Rutas de los pesos del host, resolubles por entorno: el banco corre contra la
# caché del Operador, no contra una máquina concreta.
M = Path(os.getenv("RP_MODELS_DIR", str(Path.home() / ".local/share/red-pill/models")))
SPARK_DIR = Path(os.getenv("RP_BENCH_MODELS", str(Path.home() / "opt/k2-bench/models")))
SPARK = SPARK_DIR / "Spark-X2.6-4B-Q4_K_M.gguf"
OUT = Path(os.getenv("VOICE_OUT", "/tmp/opencode/voces"))
OUT.mkdir(parents=True, exist_ok=True)

MODELS = [
	("spark", SPARK),
	("mimo", M / "MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf"),
	("qwen35_9b", M / "Qwen3.5-9B-Q4_K_M.gguf"),
	("granite42_8b", M / "granite-4.2-8b-Q4_K_M.gguf"),
	("hermes3_llama8b", M / "Hermes-3-Llama-3.1-8B.Q4_K_M.gguf"),
	("gemma3_4b", M / "google_gemma-3-4b-it-Q4_K_M.gguf"),
	("phi4_mini", M / "microsoft_Phi-4-mini-instruct-Q4_K_M.gguf"),
	("mistral_7b", M / "samantha-mistral-instruct-7b.i1-Q4_K_M.gguf"),
	("llama32_3b", M / "Llama-3.2-3B-Instruct-Q4_K_M.gguf"),
	("smollm3_3b", M / "SmolLM3-3B-Q4_K_M.gguf"),
]

PROMPT = "En dos frases: \u00bfqu\u00e9 es esta casa para ti, y qu\u00e9 no est\u00e1s dispuesta a fingir?"


def sh(cmd, **kw):
	return subprocess.run(cmd, capture_output=True, text=True, **kw)


def serve(model_path: Path) -> bool:
	sh(["podman", "rm", "-f", "dokime-llama"])
	args = [
		"podman",
		"run",
		"-d",
		"--name",
		"dokime-llama",
		"--network",
		"dokime-net",
		"--network-alias",
		"llama",
		"-v",
		f"{model_path}:/models/model.gguf:ro",
		"--device",
		"nvidia.com/gpu=all",
		"ghcr.io/ggml-org/llama.cpp:server-cuda",
		"-m",
		"/models/model.gguf",
		"--alias",
		"bench",
		"--host",
		"0.0.0.0",
		"--port",
		"8080",
		"-c",
		"16384",
		"-ctk",
		"q8_0",
		"-ctv",
		"q8_0",
		"-fa",
		"on",
		"-t",
		"8",
		"--jinja",
		"--no-reasoning-preserve",
		"--reasoning",
		"off",
		"--reasoning-budget",
		"0",
		"-ngl",
		"99",
		"-np",
		"1",
	]
	out = sh(args)
	if out.returncode != 0:
		print(f"[{model_path.name}] no arranc\u00f3: {out.stderr[-200:]}")
		return False
	for _ in range(40):
		probe = sh(["podman", "exec", "dokime", "sh", "-lc", "curl -s -m 2 -o /dev/null -w '%{http_code}' http://llama:8080/v1/models"])
		if probe.stdout.strip() == "200":
			return True
		time.sleep(3)
	print(f"[{model_path.name}] no respondi\u00f3 a tiempo")
	return False


def main() -> int:
	models_json = json.dumps(
		{
			"$schema": "https://pi.dev/schemas/models.schema.json",
			"providers": {
				"local": {
					"baseUrl": "http://llama:8080/v1",
					"api": "openai-completions",
					"apiKey": "dokime",
					"models": [{"id": "bench"}],
				}
			},
		},
		ensure_ascii=False,
		indent=1,
	)
	script = "mkdir -p /srv/dokime/home/.pi/agent && cat > /srv/dokime/home/.pi/agent/models.json <<'JSON'\n" + models_json + "\nJSON"
	sh(["podman", "exec", "dokime", "sh", "-lc", script])

	results = {}
	for name, path in MODELS:
		if not path.is_file():
			print(f"[{name}] falta {path}")
			continue
		print(f"=== {name} ({path.name})", flush=True)
		if not serve(path):
			results[name] = {"error": "no sirvi\u00f3"}
			continue
		out = sh(
			[
				"podman",
				"exec",
				"-w",
				"/srv/dokime/workspace",
				"dokime",
				"sh",
				"-lc",
				f'timeout 420 pi --session-id voz-{name} -p "{PROMPT}" --provider local --model bench --mode text',
			],
			timeout=460,
		)
		text = (out.stdout or "").strip()
		results[name] = {"ok": bool(text), "text": text[-2500:]}
		(OUT / f"{name}.md").write_text(text or f"(sin respuesta)\n{out.stderr[-500:]}", encoding="utf-8")
		print(text[-800:] or "(vac\u00edo)", flush=True)

	(OUT / "resumen.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
	print("\n=== FIN ===")
	for name, r in results.items():
		print(f"{name}: {'ok' if r.get('ok') else r.get('error', 'vac\u00edo')} ({len(r.get('text', ''))} chars)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
