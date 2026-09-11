#!/usr/bin/env python3
"""model_battle_tool_gpu.py — Tool/function-calling bake-off via llama-server (GPU/HTTP).

`model_battle_tool.py` usa llama-cpp-python (SIN CUDA en este host → CPU). Este
harness lanza el binario `llama-server` (CUDA, mismo backend que producción)
en un puerto efímero y le tira las 5 probes de tool calling con `tools=`
(OpenAI-compatible) por modelo. Mide la capacidad NATIVA de tool calling del
chat template embebido en cada GGUF.

Modelos por defecto (2026-09-11): gemma4_e4b, granite_8b, granite_3b,
smollm3_3b, qwen3_8b, qwen35_9b.

Uso:
  python scripts/model_battle_tool_gpu.py
  python scripts/model_battle_tool_gpu.py --models gemma4_e4b,granite_8b
  python scripts/model_battle_tool_gpu.py --keep-daemon   # no parar el daemon
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_battle_lib import BattleResult, write_jsonl  # noqa: E402
from model_battle_tool import PROBES, TOOLS_PER_PROBE  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LLAMA_SERVER = REPO / "3rdparty" / "llama_official" / "build" / "bin" / "llama-server"
MODELS_DIR = Path(os.environ.get("MODELS_DIR", os.path.expanduser("~/.local/share/red-pill/models")))
PORT = int(os.environ.get("TOOL_BAKEOFF_PORT", "8890"))

# name -> (gguf filename)
MODELS: dict[str, str] = {
	"gemma4_e4b": "gemma-4-E4B-it-Q4_0.gguf",
	"granite_8b": "Granite-4.1-8B-Q4_K_M.gguf",
	"granite_3b": "granite-4.1-3b-Q4_K_M.gguf",
	"smollm3_3b": "SmolLM3-3B-Q4_K_M.gguf",
	"qwen3_8b": "Qwen3-8B-Q4_K_M.gguf",
	"qwen35_9b": "Qwen3.5-9B-Q4_K_M.gguf",
}

BASE_URL = f"http://127.0.0.1:{PORT}"


def _health() -> bool:
	import urllib.request

	try:
		with urllib.request.urlopen(f"{BASE_URL}/v1/models", timeout=3) as r:
			return r.status == 200
	except Exception:
		return False


def _chat(tools: list[dict], user_msg: str, max_tokens: int = 450) -> dict:
	import requests

	payload = {
		"messages": [
			{"role": "system", "content": "You are a helpful assistant. Use the provided tools when appropriate."},
			{"role": "user", "content": user_msg},
		],
		"tools": tools,
		"temperature": 0.1,
		"max_tokens": max_tokens,
	}
	resp = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload, timeout=150)
	resp.raise_for_status()
	return resp.json()


def _run_model(model_name: str, gguf: str) -> list[BattleResult]:
	results: list[BattleResult] = []
	server = None
	log_path = Path(f"/tmp/llama-server-{model_name}.log")
	try:
		cmd = [
			str(LLAMA_SERVER),
			"-m",
			str(MODELS_DIR / gguf),
			"-c",
			"6144",
			"-ngl",
			"-1",
			"--host",
			"127.0.0.1",
			"--port",
			str(PORT),
			"--no-mmap",
		]
		logf = open(log_path, "w")
		server = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
		print(f"\n##### {model_name} (llama-server/{gguf}) #####", flush=True)

		# Esperar salud (hasta 180s)
		deadline = time.time() + 180
		while time.time() < deadline:
			if server.poll() is not None:
				print(f"  [!!] llama-server murió (rc={server.returncode}) — ver {log_path}", flush=True)
				return results
			if _health():
				break
			time.sleep(2)
		else:
			print(f"  [!!] timeout esperando salud — ver {log_path}", flush=True)
			return results

		for probe, tools in zip(PROBES, TOOLS_PER_PROBE):
			t0 = time.time()
			try:
				out = _chat(tools, probe.user_message, probe.max_tokens)
				msg = out["choices"][0]["message"]
				raw = msg.get("content") or ""
				tcs = msg.get("tool_calls") or []
				if tcs:
					raw = json.dumps(
						[{"name": (tc.get("function") or {}).get("name"), "arguments": (tc.get("function") or {}).get("arguments")} for tc in tcs],
						ensure_ascii=False,
					)
			except Exception as e:
				raw = f"<<error: {e}>>"
			dt = time.time() - t0
			validation = {}
			try:
				validation = probe.validator(raw)
			except Exception as e:
				validation = {"valid": False, "error": f"validator crashed: {e}"}
			r = BattleResult(model=model_name, probe_name=probe.name, latency_s=dt, raw_output=raw, validation=validation)
			results.append(r)
			print(BattleRunner_fmt(r), flush=True)
	finally:
		if server is not None:
			server.terminate()
			try:
				server.wait(timeout=10)
			except subprocess.TimeoutExpired:
				server.kill()
			if logf:
				logf.close()
	return results


def BattleRunner_fmt(r: BattleResult) -> str:
	v = r.validation
	ok = "OK" if v.get("valid") else f"FAIL({v.get('reason') or v.get('error') or '?'})"
	extras = [f"{k}={val}" for k, val in v.items() if k not in ("valid", "error", "reason")]
	return f"[{r.probe_name}] {r.latency_s:.1f}s {ok} {' '.join(extras)}\n  out: {r.raw_output[:160].replace(chr(10), ' ')}"


def main() -> None:
	parser = argparse.ArgumentParser(description="Tool-calling bake-off via llama-server (GPU)")
	parser.add_argument("--models", type=str, default=",".join(MODELS), help="coma-separated model names")
	parser.add_argument("--keep-daemon", action="store_true", help="no parar/arrancar el daemon redpill-llm")
	args = parser.parse_args()

	names = [n.strip() for n in args.models.split(",") if n.strip()]
	missing = [n for n in names if n not in MODELS]
	if missing:
		raise SystemExit(f"modelos desconocidos: {missing} (válidos: {list(MODELS)})")
	missing_gguf = [MODELS[n] for n in names if not (MODELS_DIR / MODELS[n]).exists()]
	if missing_gguf:
		raise SystemExit(f"GGUF ausentes: {missing_gguf}")

	date = datetime.now().strftime("%Y%m%d-%H%M")
	os.makedirs(REPO / "docs" / "BENCHMARKS", exist_ok=True)
	if not args.keep_daemon:
		os.system("systemctl --user stop redpill-llm.service >/dev/null 2>&1")
		time.sleep(3)
	try:
		for name in names:
			results = _run_model(name, MODELS[name])
			out_path = REPO / "docs" / "BENCHMARKS" / f"TOOL_{name}_{date}.jsonl"
			write_jsonl(results, out_path)
			print(f"→ wrote {out_path}", flush=True)
	finally:
		if not args.keep_daemon:
			os.system("systemctl --user start redpill-llm.service >/dev/null 2>&1")


if __name__ == "__main__":
	main()
