#!/usr/bin/env python3
"""¿Qué tools ve un cliente MCP NUEVO? — diagnóstico del kernel compartido (AD-018 §5).

Por qué existe
--------------
El kernel MCP no vive en el IDE: es un backend UDS (`redpill-mcp.service`) con un
proxy por instancia. Cuando cambia el **catálogo de tools** hay tres capas que
refrescar (backend, proxy, catálogo del cliente) y el síntoma de cada una es
distinto. Este script responde a la pregunta que las separa: *¿qué sirve el kernel
ahora mismo?* — sin gastar un turno de modelo.

Uso
---
python scripts/check_mcp_tools.py                       # lista las tools
python scripts/check_mcp_tools.py coro_api              # exige que exista
python scripts/check_mcp_tools.py --not announce_intent # exige que NO exista

Sale con 1 si la comprobación falla (sirve en CI y en un runbook).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(REPO_ROOT / ".venv" / "bin" / "python")


def default_socket() -> str:
	"""El socket del backend, por el resolvedor canónico (nunca una ruta a mano).

	`REDPILL_MCP_SOCKET` lo sobreescribe. El proxy lo recibe explícito en la config
	del IDE (verificado 2026-10-29: NO hay `mcp.sock` en `XDG_RUNTIME_DIR`).
	"""
	override = str(os.getenv("REDPILL_MCP_SOCKET") or "").strip()
	if override:
		return override
	from red_pill.core.paths import get_state_dir

	return str(get_state_dir() / "mcp.sock")


def list_tools(harness: str = "opencode") -> list[str]:
	"""Arranca un proxy efímero y devuelve el `tools/list` del backend."""
	proc = subprocess.Popen(
		[PYTHON, "-m", "red_pill.mcp_proxy", "--socket", default_socket(), "--harness", harness],
		stdin=subprocess.PIPE,
		stdout=subprocess.PIPE,
		stderr=subprocess.DEVNULL,
		text=True,
		bufsize=1,
		cwd=str(REPO_ROOT),
	)

	def send(payload: dict) -> None:
		assert proc.stdin is not None
		proc.stdin.write(json.dumps(payload) + "\n")
		proc.stdin.flush()

	def recv() -> dict:
		assert proc.stdout is not None
		line = proc.stdout.readline()
		return json.loads(line) if line.strip() else {}

	try:
		send(
			{
				"jsonrpc": "2.0",
				"id": 1,
				"method": "initialize",
				"params": {
					"protocolVersion": "2024-11-05",
					"capabilities": {},
					"clientInfo": {"name": "check_mcp_tools", "version": "1"},
				},
			}
		)
		recv()
		send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
		send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
		result = recv().get("result") or {}
		return [str(t.get("name")) for t in result.get("tools") or []]
	finally:
		proc.terminate()


def main(argv: list[str]) -> int:
	must: list[str] = []
	must_not: list[str] = []
	target = must
	for arg in argv:
		if arg in ("--not", "--absent"):
			target = must_not
			continue
		target.append(arg)

	try:
		names = list_tools()
	except Exception as exc:  # backend caído: es el diagnóstico, no un crash
		print(f"ERROR: no se pudo hablar con el backend MCP: {exc}")
		return 1

	print(f"{len(names)} tools: " + ", ".join(sorted(names)))

	status = 0
	for name in must:
		if name not in names:
			print(f"FALTA: {name}")
			status = 1
	for name in must_not:
		if name in names:
			print(f"SIGUE PRESENTE: {name}")
			status = 1
	if status == 0 and (must or must_not):
		print("OK")
	return status


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))
