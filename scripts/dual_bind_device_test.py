#!/usr/bin/env python3
"""DB-001 — prueba de ida y vuelta de la palanca de carril del dual_bind.

Ejercita `POST /control/device` contra el proxy real:

	cpu (inicial) → gpu (pre-heat) → cpu (pre-heat) → auto

En cada salto comprueba el `mode` de `/status` y lanza un ping al modelo, para
probar que la **siguiente petición** va al destino nuevo. Al final restaura el
modo inicial (o `auto`). No toca el `.env` ni reinicia nada.

Uso:
	python3 scripts/dual_bind_device_test.py [--base http://localhost:8760]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _req(method: str, url: str, body: dict | None = None, timeout: float = 240.0) -> dict:
	data = json.dumps(body).encode("utf-8") if body is not None else None
	req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
	try:
		with urllib.request.urlopen(req, timeout=timeout) as resp:
			return json.loads(resp.read().decode("utf-8"))
	except urllib.error.HTTPError as e:
		try:
			return json.loads(e.read().decode("utf-8"))
		except Exception:
			return {"error": f"HTTP {e.code}"}


def status(base: str) -> dict:
	return _req("GET", f"{base}/status", timeout=10)


def set_device(base: str, device: str, wait: bool = True) -> dict:
	return _req("POST", f"{base}/control/device", {"device": device, "wait": wait})


def ping(base: str, model: str) -> dict:
	return _req(
		"POST",
		f"{base}/v1/chat/completions",
		{"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1, "temperature": 0},
	)


def _mode(base: str) -> str | None:
	return status(base).get("mode")


def main(argv: list | None = None) -> int:
	parser = argparse.ArgumentParser(description="DB-001 — round-trip GPU/CPU del dual_bind")
	parser.add_argument("--base", default="http://localhost:8760")
	args = parser.parse_args(argv)
	base = args.base.rstrip("/")
	failures: list[str] = []

	initial = status(base)
	initial_mode = initial.get("mode")
	print(f"[db001] inicial: mode={initial_mode} model={initial.get('loaded_model')}")

	def step(name: str, device: str, expect: str) -> bool:
		started = time.time()
		result = set_device(base, device, wait=True)
		elapsed = time.time() - started
		detail = result.get("error") or result.get("preheat")
		ok = bool(result.get("ok")) and _mode(base) == expect
		# La siguiente petición debe ir al destino nuevo.
		if ok:
			model = status(base).get("loaded_profile") or "granite_8b"
			reply = ping(base, model)
			ok = bool(reply.get("choices"))
			detail = f"{detail} · ping_ok={ok}"
		print(f"[db001] {name:<28} device={device:<3} mode={_mode(base)} {elapsed:5.1f}s · {detail}")
		if not ok:
			failures.append(name)
		return ok

	step("cpu (base)", "cpu", "cpu")
	step("gpu (pre-heat)", "gpu", "gpu")
	step("cpu (vuelta)", "cpu", "cpu")

	# Restaurar: el modo inicial si era gpu/cpu; si no, auto.
	if initial_mode in ("gpu", "cpu"):
		restore = set_device(base, initial_mode, wait=True)
		print(f"[db001] restaurar {initial_mode}: {restore.get('error') or 'ok'}")
	else:
		restore = set_device(base, "auto", wait=False)
		print(f"[db001] restaurar auto: {restore.get('error') or 'ok'}")

	if failures:
		print(f"[db001] FALLOS: {', '.join(failures)}")
		return 1
	print("[db001] OK — ida y vuelta completa")
	return 0


if __name__ == "__main__":
	sys.exit(main())
