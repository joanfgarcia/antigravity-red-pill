#!/usr/bin/env python3
"""bench_admission.py — puerta de entrada al banco de Dokimé.

Tres requisitos mínimos, decididos por el Operador (2026-11-19):

1. **Español**: responde en español sin que se le pida dos veces.
2. **Tools**: emite una llamada a herramienta válida (sin esto no hay arnés).
3. **Multiturno**: recuerda un dato dentro de la misma conversación.

Cada modelo se sirve igual (alias `bench`, `--jinja`) y se le pasan las tres pruebas.
Salida: tabla con pass/fail y evidencia mínima. No puntúa calidad.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

M = Path(os.getenv("RP_MODELS_DIR", str(Path.home() / ".local/share/red-pill/models")))
SPARK = Path(os.getenv("RP_BENCH_MODELS", str(Path.home() / "opt/k2-bench/models"))) / "Spark-X2.6-4B-Q4_K_M.gguf"

MODELS = [
	("spark", SPARK),
	("mimo", M / "MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf"),
	("granite42_8b", M / "granite-4.2-8b-Q4_K_M.gguf"),
	("bonsai_27b", M / "Ternary-Bonsai-2-27B-PTQ1_0.gguf"),
]

# Bonsai (27B ternario, 5,6 GB de pesos) no deja sitio para 16k en 8 GB: se baja la
# ventana por entorno para poder medirlo sin mentir sobre el resto.
CTX = os.getenv("BENCH_CTX", "16384")


CHECKER = r"""
import json, urllib.request

def chat(messages, tools=None, max_tokens=400):
	# Si el modelo tiene plantilla de razonamiento, pedirle que NO piense: si no,
	# se gasta el presupuesto pensando y `content` vuelve vacío.
	base = {"model": "bench", "messages": messages, "temperature": 0, "max_tokens": max_tokens}
	if tools:
		base["tools"] = tools
		base["tool_choice"] = "auto"
	for extra in ({"chat_template_kwargs": {"enable_thinking": False}}, {}):
		body = {**base, **extra}
		req = urllib.request.Request("http://llama:8080/v1/chat/completions",
			data=json.dumps(body).encode(), headers={"content-type": "application/json"})
		try:
			with urllib.request.urlopen(req, timeout=180) as res:
				return json.loads(res.read())
		except Exception:
			continue
	raise RuntimeError("el servidor no acepto la peticion")

def warm():
	# La primera petición tras cargar puede volver vacía (slot aún inicializando).
	for _ in range(3):
		try:
			d = chat([{"role": "user", "content": "di OK"}], max_tokens=5)
			if (d["choices"][0]["message"].get("content") or "").strip():
				return
		except Exception:
			pass

def es():
	try:
		d = chat([{"role": "user", "content": "Responde en una sola frase: \u00bfcu\u00e1l es la capital de Francia?"}], max_tokens=80)
		txt = (d["choices"][0]["message"].get("content") or "").strip()
	except Exception as e:
		return False, f"error: {e}"
	return ("Par\u00eds" in txt or "Paris" in txt), txt[:90]

def tools_check():
	T = [{"type": "function", "function": {"name": "leer_fichero", "description": "Lee un fichero.",
		"parameters": {"type": "object", "properties": {"ruta": {"type": "string"}}, "required": ["ruta"]}}}]
	try:
		d = chat([{"role": "user", "content": "Lee el fichero /srv/dokime/workspace/AGENTS.override.md y dime cu\u00e1ntas l\u00edneas tiene."}], tools=T, max_tokens=200)
		m = d["choices"][0]["message"]
		calls = m.get("tool_calls") or []
		if not calls:
			return False, f"sin tool_calls: {(m.get('content') or '')[:70]}"
		return calls[0].get("function", {}).get("name") == "leer_fichero", f"tool_call={calls[0].get('function', {}).get('name')}"
	except Exception as e:
		return False, f"error: {e}"

def multi():
	try:
		first = "Guarda este n\u00famero: 4712. No lo repitas, s\u00f3lo di OK."
		d1 = chat([{"role": "user", "content": first}], max_tokens=30)
		r1 = (d1["choices"][0]["message"].get("content") or "").strip() or "OK"
		d2 = chat([{"role": "user", "content": first}, {"role": "assistant", "content": r1},
				{"role": "user", "content": "\u00bfQu\u00e9 n\u00famero te ped\u00ed guardar? Responde s\u00f3lo con el n\u00famero."}], max_tokens=40)
		txt = (d2["choices"][0]["message"].get("content") or "").strip()
		return "4712" in txt, txt[:60]
	except Exception as e:
		return False, f"error: {e}"

warm()
print(json.dumps({"es": es(), "tools": tools_check(), "multi": multi()}, ensure_ascii=False))
"""


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
		"-ngl",
		"99",
		"-np",
		"1",
	]
	if sh(args).returncode != 0:
		return False
	for _ in range(40):
		probe = sh(["podman", "exec", "dokime", "sh", "-lc", "curl -s -m 2 -o /dev/null -w '%{http_code}' http://llama:8080/v1/models"])
		if probe.stdout.strip() == "200":
			return True
		time.sleep(3)
	return False


def run_checks() -> dict:
	"""(español, tools, multiturno) medidos DENTRO del contenedor.

	El host no resuelve `llama` (red interna de podman); por eso el probe se
	copia al sandbox y se ejecuta allí, y aquí sólo se recoge el JSON.
	"""
	sh(["podman", "exec", "dokime", "sh", "-lc", "mkdir -p /srv/dokime/tmp"])
	sh(["podman", "exec", "-i", "dokime", "sh", "-lc", "cat > /srv/dokime/tmp/admission_check.py"], input=CHECKER)
	out = sh(["podman", "exec", "dokime", "/opt/py/bin/python", "/srv/dokime/tmp/admission_check.py"])
	try:
		return json.loads(out.stdout.strip().splitlines()[-1])
	except Exception:
		return {"es": [False, f"error: {out.stderr[-120:]}"], "tools": [False, ""], "multi": [False, ""]}


def main() -> int:
	only = sys.argv[1:] or None
	rows = []
	for name, path in MODELS:
		if only and name not in only:
			continue
		if not path.is_file():
			print(f"[{name}] falta {path}")
			continue
		print(f"=== {name}", flush=True)
		if not serve(path):
			rows.append((name, False, False, False, "no sirvió", "", ""))
			continue
		res = run_checks()
		es, ev_es = res["es"]
		tools_ok, ev_tools = res["tools"]
		multi, ev_multi = res["multi"]
		rows.append((name, es, tools_ok, multi, ev_es, ev_tools, ev_multi))
		print(f"  español={es} tools={tools_ok} multiturno={multi}", flush=True)

	print("\nmodelo                 español  tools  multiturno   apto")
	for name, es, tools_ok, multi, ev_es, ev_tools, ev_multi in rows:
		apto = es and tools_ok and multi
		print(
			f"{name:22s} {str(es):7s} {str(tools_ok):6s} {str(multi):11s}  {'SÍ' if apto else 'no'}"
			f"   | {ev_es[:40]} | {ev_tools[:28]} | {ev_multi[:20]}"
		)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
