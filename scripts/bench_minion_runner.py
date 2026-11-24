#!/usr/bin/env python3
"""Brazo `minion` del experimento de calidad (Dokimé vs Pi bare vs minion).

Se ejecuta DENTRO de la caja. Registra un proveedor OpenAI-TCP contra el mismo
`llama:8080` que usa Dokimé, deja al minion sólo con `run_bash` y ejecuta una
tarea del fixture. Imprime un JSON con la respuesta y el uso de tools.

Uso (dentro):
	PYTHONPATH=/src/red-pill/src python /src/red-pill/scripts/bench_minion_runner.py \
		--cwd /srv/dokime/bench --prompt "¿Cuántos ficheros .py hay bajo src/? Sólo el número."
"""

from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import sys


def _provider_class():
	from red_pill.core.providers import BaseInferenceProvider

	class BenchProvider(BaseInferenceProvider):
		"""OpenAI-compatible TCP contra el llama-server del sandbox."""

		def __init__(self, host: str = "llama", port: int = 8080, model: str = "spark"):
			self.host = host
			self.port = port
			self.model = model

		def generate(self, prompt: str, **kwargs) -> str:
			return str(self.chat([{"role": "user", "content": prompt}], **kwargs).get("content") or "")

		def stream(self, prompt: str, **kwargs):
			return iter(())

		def chat(self, messages, *, tools=None, tool_choice=None, temperature=0.8, max_tokens=1024, response_format=None, timeout=600):
			# Mismos parámetros que el brazo Pi (`models.json`): el servidor es el
			# mismo, así que la única diferencia es el arnés.
			payload = {
				"model": self.model,
				"messages": messages,
				"temperature": 0.8,
				"top_p": 0.95,
				"max_tokens": 1024,
				"seed": 42,
			}
			if tools:
				payload["tools"] = tools
				payload["tool_choice"] = tool_choice or "auto"
			conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
			conn.request("POST", "/v1/chat/completions", body=json.dumps(payload), headers={"Content-Type": "application/json"})
			response = conn.getresponse()
			raw = response.read().decode(errors="replace")
			try:
				data = json.loads(raw)
			except ValueError as exc:
				raise RuntimeError(f"llama-server no devolvió JSON (HTTP {response.status}): {raw[:300]}") from exc
			choices = data.get("choices") if isinstance(data, dict) else None
			if not choices:
				raise RuntimeError(f"llama-server sin choices (HTTP {response.status}): {raw[:300]}")
			return choices[0]["message"]

	return BenchProvider


async def _run(cwd: str, prompt: str) -> dict:
	from red_pill.core.providers import ProviderRegistry
	from red_pill.swarm.agents import local_minion

	BenchProvider = _provider_class()
	ProviderRegistry.register_inference_provider("bench", BenchProvider())

	# Igualdad de tools: el minion sólo ve `run_bash`; sin MCP, sin read/write.
	local_minion.TOOLS = [t for t in local_minion.TOOLS if t["function"]["name"] == "run_bash"]
	result = await local_minion.run_local_minion(prompt, cwd=cwd, provider_name="bench")
	return {
		"ok": bool(result.get("ok")),
		"answer": str(result.get("answer") or ""),
		"steps": int(result.get("steps") or 0),
		"used_tools": bool(result.get("used_tools")),
		"tool_calls": int(result.get("tool_calls") or 0),
		"error": result.get("error"),
		"messages": result.get("messages"),
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--cwd", required=True)
	ap.add_argument("--prompt", required=True)
	args = ap.parse_args()
	sys.path.insert(0, "/src/red-pill/src")
	try:
		print(json.dumps(asyncio.run(_run(args.cwd, args.prompt)), ensure_ascii=False))
	except Exception as exc:  # noqa: BLE001 — el runner reporta, no tumba el bench
		print(json.dumps({"ok": False, "answer": "", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
