#!/usr/bin/env python3
"""Multiturno de herramientas REAL: llamada → resultado → ¿sigue?

El probe `multi_step` del arnés de bake-off pedía **dos llamadas en UNA
respuesta** y nunca devolvía el resultado de la herramienta. Eso no mide
multiturno: mide paralelismo. Un modelo que llama `list_dir`, espera y para está
haciendo lo correcto — y allí contaba como FAIL (2026-10-30, corregido aquí).

Este probe hace el bucle de verdad contra un `llama-server` (o cualquier
endpoint OpenAI-compatible): manda `tools`, recibe `tool_calls`, devuelve un
resultado simulado con `role: tool`, y repite hasta que el modelo responde sin
herramientas. Lo que se mide es **si encadena**, cuántas vueltas y si la
respuesta final usa el contenido que se le devolvió.

Uso:
    python scripts/tool_loop_probe.py --port 30130
    python scripts/tool_loop_probe.py --port 30130 --vueltas 5 --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

TOOLS = [
    {"type": "function", "function": {"name": "list_dir", "description": "Lista los ficheros de un directorio.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "grep", "description": "Busca un patrón en ficheros.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                    "required": ["pattern", "path"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Lee un fichero.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]

# Contenido SINTÉTICO: así el resultado se reconoce en la respuesta final y se
# distingue "usó la herramienta" de "se lo inventó".
RESULTADOS = {
    "list_dir": "src/a.py\nsrc/b.js\nsrc/c.py\nREADME.md",
    "grep": "src/a.py:12: async def foo()\nsrc/c.py:3: async def bar()",
    "read_file": "1: import os\n2: async def foo():\n3:     pass",
}

ESCENARIOS = [
    ("A · buscar en un directorio", "Encuentra todas las funciones async que haya en src/. Usa las herramientas."),
    ("B · preguntar cuántas", "¿Cuántas funciones async hay en src/?"),
    ("C · mirar un fichero concreto", "Mira src/a.py y dime si contiene funciones async."),
]


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=900).read())


def bucle(url: str, nombre: str, primer_user: str, vueltas: int) -> dict:
    msgs = [
        {"role": "system", "content": "Eres un agente. Usa las herramientas para completar la tarea y para cuando la tengas."},
        {"role": "user", "content": primer_user},
    ]
    traza, uso_resultado, respondio = [], False, False
    print(f"\n===== {nombre} =====")
    for v in range(vueltas):
        t0 = time.time()
        r = _post(url, {"messages": msgs, "tools": TOOLS, "tool_choice": "auto", "temperature": 0.0, "max_tokens": 400})
        msg = r["choices"][0]["message"]
        tcs = msg.get("tool_calls") or []
        dt = time.time() - t0
        if not tcs:
            contenido = msg.get("content") or ""
            # ¿la respuesta final cita el contenido devuelto? (foo/bar vienen del resultado)
            uso_resultado = any(x in contenido for x in ("foo", "bar"))
            print(f"  vuelta {v + 1} ({dt:.1f}s): SIN tool_calls → {contenido[:110]!r}")
            traza.append({"vuelta": v + 1, "sin_tool_calls": True, "content": contenido, "s": round(dt, 2)})
            respondio = True
            break
        nombres = [tc["function"]["name"] for tc in tcs]
        print(f"  vuelta {v + 1} ({dt:.1f}s): {nombres}")
        traza.append({"vuelta": v + 1, "tools": nombres, "s": round(dt, 2)})
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
        for tc in tcs:
            fn = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except Exception:
                args = {}
            salida = RESULTADOS.get(fn, "(sin resultado)")
            print(f"      → {fn}({json.dumps(args, ensure_ascii=False)}) = {salida.splitlines()[0][:60]}")
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": salida})
    else:
        print("  (agotadas las vueltas sin respuesta final)")
    # `pasos` = llamadas a herramientas. Encadenar no es "hacer muchas": en C la
    # tarea se resuelve con UNA lectura y parar es lo correcto. La señal de que el
    # bucle funciona es (a) llega a respuesta final y (b) esa respuesta usa el
    # contenido que se le devolvió (foo/bar salen del resultado sintético).
    pasos = sum(1 for x in traza if x.get("tools"))
    return {"escenario": nombre, "pasos": pasos, "llego_a_respuesta": respondio,
            "uso_resultado": uso_resultado, "traza": traza}


def main() -> None:
    ap = argparse.ArgumentParser(description="Multiturno de herramientas real")
    ap.add_argument("--port", type=int, default=30130)
    ap.add_argument("--vueltas", type=int, default=4)
    ap.add_argument("--json", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/v1/chat/completions"

    res = [bucle(url, n, u, args.vueltas) for n, u in ESCENARIOS]
    print(f"\n{'escenario':32s} {'pasos':>6s} {'responde':>9s} {'usa resultado':>14s}")
    for r in res:
        print(f"{r['escenario']:32s} {r['pasos']:6d} {('SÍ' if r['llego_a_respuesta'] else 'no'):>9s} "
              f"{('SÍ' if r['uso_resultado'] else 'no'):>14s}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print(f"\njson: {args.json}")
    if not all(r["llego_a_respuesta"] and r["uso_resultado"] for r in res):
        sys.exit(1)


if __name__ == "__main__":
    main()
