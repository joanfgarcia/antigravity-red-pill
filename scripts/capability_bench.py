"""Banco de capacidades: ¿siguen funcionando TODAS las tools, y cuánto cuesta arrancar?

Dos preguntas, una pasada, sin modelo de por medio (determinista):

1. **Plomería**: conecta al backend por el MISMO transporte que usa el arnés
	(MCP sobre HTTP en el socket Unix), lista las tools, y llama a cada una con
	un payload mínimo válido. Distingue:
		ok        → la tool respondió
		tool_err  → la tool respondió con error *de negocio* (plomería bien)
		FAIL      → excepción, timeout o tool ausente (esto es lo que rompe el arnés)

2. **Presupuesto de arranque**: pide `/hook/context` en `full` y en `light` y
	cuenta TOKENS reales (tokenizer del servidor, con fallback chars/3.7). Es el
	número que el Operador quiere bajar sin perder capacidad.

Corre DENTRO del sandbox (el socket vive ahí):

	podman exec -w /srv/dokime/workspace dokime sh -lc \
		'PYTHONPATH=/src/red-pill/src /opt/py/bin/python /src/red-pill/scripts/capability_bench.py'

Salida: tabla + JSON. Código 3 si alguna tool no responde (nunca "0 silencioso").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any, Dict, List

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SOCKET = "/srv/dokime/xdg/data/red-pill/state/mcp.sock"
LLAMA = "http://llama:8080/v1/tokenize"
ESTIMATE_RATIO = 3.7

# Payloads mínimos. La intención NO es que la operación tenga éxito de negocio
# (no hay una decisión que revisar), sino que la tool exista, valide el esquema y
# conteste sin tumbar el backend. `tool_err` es un aprobado.
CALLS: Dict[str, Dict[str, Any]] = {
	"sovereign_handshake": {"user_prompt": "probe de capacidades"},
	"bunker_memory_api": {"action": "read_core_directives", "payload": {}},
	"coro_api": {"action": "fetch", "payload": {"limit": 1}},
	"job_manager_api": {"action": "job_list", "payload": {"limit": 1}},
	"metabolism_health_api": {"action": "get_hardware_status", "payload": {}},
	"swarm_orchestrator_api": {"action": "check_minion_inbox", "payload": {}},
	"redpill_search": {"query": "identidad"},
	"redpill_call": {"name": "list_decisions", "arguments": {}},
	"review_decision": {"action": "list"},
	"suggest_review": {"verdict": "approve"},
	"list_decisions": {},
	"moderate_note": {"event_id": "probe-inexistente", "action": "flag", "reason": "probe de capacidades"},
	"fetch_divergent_turns": {},
	"try_claim_stage": {},
}
# Tools donde un error de negocio es lo normal (faltan ids/estado): no es fallo.
EXPECTED_TOOL_ERR = {
	"review_decision",
	"suggest_review",
	"moderate_note",
	"try_claim_stage",
}
# NO se invocan: tocan estado real de otra sesión.
# `unregister_session` no recibe argumentos y resuelve el leg por el bridge (el
# ÚLTIMO que escribió): la primera versión de este banco cerró la sesión viva de
# otro proceso. Se valida que existe y que su esquema es el esperado; no se llama.
SKIP = {"unregister_session"}


def _fill(schema: Dict[str, Any]) -> Dict[str, Any]:
	out: Dict[str, Any] = {}
	for name in schema.get("required") or []:
		prop = (schema.get("properties") or {}).get(name) or {}
		t = prop.get("type")
		out[name] = {"string": "", "boolean": False, "integer": 1, "number": 1, "array": [], "object": {}}.get(t, "")
	return out


async def _tokens(client: httpx.AsyncClient, text: str) -> int:
	try:
		r = await client.post(LLAMA, json={"content": text}, timeout=10)
		if r.status_code == 200:
			return int(r.json().get("tokens") or 0)
	except Exception:
		pass
	return int(len(text) / ESTIMATE_RATIO)


async def _budget(client: httpx.AsyncClient, sock: str, need: str) -> Dict[str, Any]:
	payload = {
		"harness": "pi",
		"session_id": "cap-probe",
		"need": need,
		"prompt": "¿quién soy y qué memoria tengo?" if need == "light" else "",
		"turn": 1,
	}
	transport = httpx.AsyncHTTPTransport(uds=sock)
	async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as c:
		r = await c.post("/hook/context", json=payload, timeout=60)
		data = r.json()
	blocks = data.get("blocks") or []
	total = "".join(str(b.get("text") or "") for b in blocks)
	return {
		"need": need,
		"blocks": [{"kind": b.get("kind"), "chars": len(str(b.get("text") or ""))} for b in blocks],
		"chars": len(total),
		"tokens": await _tokens(client, total),
	}


async def main(sock: str, expect: int, via_call: bool) -> int:
	transport = httpx.AsyncHTTPTransport(uds=sock)
	http = httpx.AsyncClient(transport=transport, base_url="http://localhost")
	rows: List[Dict[str, Any]] = []

	async with streamablehttp_client("http://localhost/mcp", httpx_client_factory=lambda **kw: http) as (r, w, _):
		async with ClientSession(r, w) as s:
			await s.initialize()
			tools = (await s.list_tools()).tools
			names = [t.name for t in tools]
			print(f"tools: {len(names)} → {', '.join(names)}\n")

			missing = [n for n in CALLS if n not in names]
			for name in names:
				if name in SKIP:
					rows.append({"tool": name, "verdict": "skip", "ms": 0, "chars": 0, "sample": "destructivo: sólo se valida esquema"})
					print(f"  {'skip':<9} {name:<26} {'—':>6}     destructivo, no se ejecuta")
					continue
				args = CALLS.get(name) or _fill(next((t.inputSchema for t in tools if t.name == name) or {}, {}))
				t0 = time.time()
				try:
					if via_call and name not in ("redpill_call", "redpill_search"):
						# La pregunta que importa del perfil `gateway`: ¿llego a TODAS
						# por la puerta única aunque sólo 3 estén declaradas?
						res = await asyncio.wait_for(s.call_tool("redpill_call", {"name": name, "arguments": args}), timeout=90)
					else:
						res = await asyncio.wait_for(s.call_tool(name, args), timeout=90)
					ms = int((time.time() - t0) * 1000)
					text = " ".join(getattr(c, "text", "") for c in (res.content or [])) if res.content else ""
					if res.isError:
						verdict = "ok*" if name in EXPECTED_TOOL_ERR else "tool_err"
					else:
						verdict = "ok"
				except Exception as exc:  # noqa: BLE001 — se reporta, no se maquilla
					ms = int((time.time() - t0) * 1000)
					verdict, text = "FAIL", f"{type(exc).__name__}: {exc}"[:120]
				rows.append({"tool": name, "verdict": verdict, "ms": ms, "chars": len(text), "sample": text[:80]})
				print(f"  {verdict:<9} {name:<26} {ms:>6} ms  {text[:60]}")

	budget = {}
	for need in ("full", "light"):
		try:
			budget[need] = await _budget(http, sock, need)
			print(f"\ncontexto {need}: {budget[need]['tokens']} tok · {budget[need]['chars']} chars · {[b['kind'] for b in budget[need]['blocks']]}")
		except Exception as exc:  # noqa: BLE001
			print(f"\ncontexto {need}: FAIL {exc}")

	fails = [r for r in rows if r["verdict"] == "FAIL"]
	missing += [r["tool"] for r in fails if r["tool"] not in missing]
	out = {"tools": len(rows), "expected": expect, "missing": missing, "rows": rows, "budget": budget}
	print("\n" + json.dumps({"tools": len(rows), "missing": missing, "fails": [r["tool"] for r in fails]}, ensure_ascii=False))
	print(json.dumps(out, ensure_ascii=False))
	return 3 if fails or missing or len(rows) != expect else 0


if __name__ == "__main__":
	ap = argparse.ArgumentParser()
	ap.add_argument("--socket", default=SOCKET)
	ap.add_argument("--expect", type=int, default=15)
	ap.add_argument("--via-redpill-call", action="store_true", help="alcanza cada tool por la puerta única (perfil gateway)")
	a = ap.parse_args()
	raise SystemExit(asyncio.run(main(a.socket, a.expect, a.via_redpill_call)))
