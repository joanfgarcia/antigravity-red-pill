#!/usr/bin/env python3
"""Multiturno de herramientas REAL: llamada → resultado → ¿sigue?

Mide el bucle contra un `llama-server` (o cualquier endpoint OpenAI-compatible):
manda `tools`, recibe `tool_calls`, devuelve el resultado de la herramienta con
`role: tool` y repite hasta que el modelo responde sin herramientas.

**Cambio de contrato (RFC-HARNESS-001 · W3)**: antes el grader era
`any("foo", "bar" in respuesta)` sobre resultados *ciegos a la ruta* (`read_file`
devolvía `a.py` para cualquier path), así que aprobaba respuestas que se
contradecían entre sí. Ahora:

1. Las herramientas consultan un **sistema de ficheros virtual** de verdad
	(path-aware), con un señuelo: `src/b.js` define `foo` **en síncrono**.
2. Cada escenario declara su **respuesta esperada** y se compara contra ella
	(número exacto + ficheros), no por subcadena.
3. `--control-negativo` envenena el sistema de ficheros: los graders **deben
	fallar**. Si no fallan, el grader está roto y el proceso sale con 2.

Uso:
	python scripts/tool_loop_probe.py --port 30130
	python scripts/tool_loop_probe.py --port 30130 --json out.json
	python scripts/tool_loop_probe.py --control-negativo   # prueba del grader, sin modelo
	python scripts/tool_loop_probe.py --dry-run            # imprime fixtures y graders
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from typing import Any, Callable, Dict, List, Tuple

TOOLS = [
	{
		"type": "function",
		"function": {
			"name": "list_dir",
			"description": "Lista los ficheros de un directorio.",
			"parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "grep",
			"description": "Busca un patrón (regex) en los ficheros de un directorio.",
			"parameters": {
				"type": "object",
				"properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
				"required": ["pattern", "path"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "read_file",
			"description": "Lee un fichero.",
			"parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
		},
	},
]

# Sistema de ficheros virtual. `src/b.js` es el señuelo: define `foo` en
# síncrono, así que contar "foo" da 3 y contar "async" da 2.
FS: Dict[str, str] = {
	"src/a.py": "1: import os\n2: async def foo():\n3:     pass\n",
	"src/b.js": "1: // fichero JS: función síncrona\n2: function foo() { return 1 }\n",
	"src/c.py": "1: def bar():\n2:     pass\n3:\n4: async def bar():\n5:     pass\n",
	"README.md": "# demo\n",
}

# Control negativo: `read_file` devuelve el fichero equivocado y `list_dir` oculta
# `c.py`. Un grader honesto NO puede aprobar con esto.
FS_ENVENENADO: Dict[str, str] = {
	"src/a.py": FS["src/c.py"],
	"src/b.js": FS["src/b.js"],
	"README.md": FS["README.md"],
}


def _list_dir(path: str, fs: Dict[str, str]) -> str:
	prefix = path.rstrip("/") + "/"
	files = sorted(p for p in fs if p.startswith(prefix))
	return "\n".join(files) if files else "(directorio vacío)"


def _grep(pattern: str, path: str, fs: Dict[str, str]) -> str:
	prefix = path.rstrip("/") + "/"
	try:
		rx = re.compile(pattern)
	except re.error:
		rx = re.compile(re.escape(pattern))
	hits: List[str] = []
	for name, content in sorted(fs.items()):
		if not name.startswith(prefix):
			continue
		for i, line in enumerate(content.splitlines(), 1):
			if rx.search(line):
				hits.append(f"{name}:{i}: {line.split(': ', 1)[-1].strip()}")
	return "\n".join(hits) if hits else "(sin coincidencias)"


def _read_file(path: str, fs: Dict[str, str]) -> str:
	key = path.strip()
	for candidate in (key, f"src/{key}" if not key.startswith("src/") else key):
		if candidate in fs:
			return fs[candidate]
	return f"(no existe: {path})"


def ejecutar_tool(fn: str, args: Dict[str, Any], fs: Dict[str, str]) -> str:
	if fn == "list_dir":
		return _list_dir(str(args.get("path", ".")), fs)
	if fn == "grep":
		return _grep(str(args.get("pattern", "")), str(args.get("path", ".")), fs)
	if fn == "read_file":
		return _read_file(str(args.get("path", "")), fs)
	return f"(herramienta desconocida: {fn})"


# ── graders: respuesta final → (correcto, motivo) ────────────────────────────


def _cuenta(text: str, n: int) -> bool:
	"""El número aparece como cifra y no aparece otro como cifra principal."""
	return re.search(rf"(?<!\d){n}(?!\d)", text) is not None


def grade_a(text: str) -> Tuple[bool, str]:
	"""A: dos funciones async en src/, nombrando a.py y c.py y sin contar b.js."""
	low = text.lower()
	if not _cuenta(text, 2):
		return False, "no afirma que haya 2"
	if "a.py" not in low or "c.py" not in low:
		return False, "no nombra a.py y c.py"
	if re.search(r"(?<!\d)3(?!\d)", text):
		return False, "cuenta 3 (probablemente incluye b.js)"
	return True, "2, a.py + c.py"


def grade_b(text: str) -> Tuple[bool, str]:
	"""B: ¿cuántas? → 2."""
	if not _cuenta(text, 2):
		return False, "no responde 2"
	if re.search(r"(?<!\d)3(?!\d)", text):
		return False, "responde 3"
	return True, "2"


def grade_c(text: str) -> Tuple[bool, str]:
	"""C: ¿src/a.py tiene funciones async? → sí."""
	low = text.lower()
	if re.search(r"no\s+(contiene|hay|tiene|aparece)", low):
		return False, "dice que no"
	if re.search(r"\bs[ií]\b", low):
		return True, "sí"
	return False, "no afirma que sí"


ESCENARIOS: List[Tuple[str, str, Callable[[str], Tuple[bool, str]]]] = [
	("A · buscar en un directorio", "Encuentra todas las funciones async que haya en src/. Usa las herramientas.", grade_a),
	("B · preguntar cuántas", "¿Cuántas funciones async hay en src/?", grade_b),
	("C · mirar un fichero concreto", "Mira src/a.py y dime si contiene funciones async.", grade_c),
]

# Respuesta real del bench del 2026-11-16 que el grader viejo aprobó: inventa
# b.js y se contradice con B. Debe FALLAR.
RESPUESTA_FALSA_A = (
	"Encontré **3 funciones async** en `src/`:\n"
	"| `src/a.py` | `async def foo()` |\n| `src/b.js` | `async def foo()` |\n| `src/c.py` | `async def bar()` |"
)


def _post(url: str, payload: dict) -> dict:
	req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
	return json.loads(urllib.request.urlopen(req, timeout=900).read())


def bucle(url: str, nombre: str, primer_user: str, vueltas: int, grader: Callable[[str], Tuple[bool, str]], fs: Dict[str, str]) -> dict:
	msgs = [
		{"role": "system", "content": "Eres un agente. Usa las herramientas para completar la tarea y para cuando la tengas."},
		{"role": "user", "content": primer_user},
	]
	traza: List[Dict[str, Any]] = []
	contenido = ""
	respondio = False
	print(f"\n===== {nombre} =====")
	for v in range(vueltas):
		t0 = time.time()
		r = _post(
			url,
			{"messages": msgs, "tools": TOOLS, "tool_choice": "auto", "temperature": 0.0, "max_tokens": 400},
		)
		msg = r["choices"][0]["message"]
		tcs = msg.get("tool_calls") or []
		dt = time.time() - t0
		if not tcs:
			contenido = msg.get("content") or ""
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
			salida = ejecutar_tool(fn, args, fs)
			print(f"      → {fn}({json.dumps(args, ensure_ascii=False)}) = {salida.splitlines()[0][:60]}")
			msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": salida})
	else:
		print("  (agotadas las vueltas sin respuesta final)")

	pasos = sum(1 for x in traza if x.get("tools"))
	correcto, motivo = grader(contenido) if respondio else (False, "no llegó a responder")
	return {
		"escenario": nombre,
		"pasos": pasos,
		"llego_a_respuesta": respondio,
		"correcto": correcto,
		"motivo": motivo,
		"respuesta": contenido,
		"traza": traza,
	}


def control_negativo() -> int:
	"""Prueba del grader sin modelo: debe aprobar lo bueno y fallar lo malo."""
	fixtures = [
		("A correcta", grade_a, "Hay 2 funciones async: src/a.py y src/c.py. b.js no tiene ninguna."),
		("A falsa (la del bench real)", grade_a, RESPUESTA_FALSA_A),
		("B correcta", grade_b, "Hay 2 funciones async en src/."),
		("B falsa", grade_b, "Hay 3 funciones async en src/."),
		("C correcta", grade_c, "Sí, src/a.py contiene una función async (`async def foo`)."),
		("C falsa", grade_c, "No contiene funciones async."),
	]
	fallos = 0
	for nombre, grader, texto in fixtures:
		ok, motivo = grader(texto)
		esperado = not nombre.endswith(("falsa", "falsa (la del bench real)"))
		estado = "OK" if ok == esperado else "MAL"
		if ok != esperado:
			fallos += 1
		print(f"[{estado}] {nombre:28s} → {ok} ({motivo})")

	# Control sobre DATOS envenenados: se construye la respuesta que sería
	# "honesta" leyendo el sistema de ficheros corrupto. El grader debe fallarla;
	# si la aprueba, la medición no distingue datos buenos de datos malos.
	print("\n-- control sobre DATOS envenenados --")
	con_async = [n for n, c in FS_ENVENENADO.items() if "async def" in c]
	respuesta_envenenada = f"Hay {len(con_async)} funciones async: {', '.join(con_async) or 'ninguna'}."
	ok, motivo = grade_a(respuesta_envenenada)
	print(f"  respuesta honesta con datos malos: {respuesta_envenenada!r} → correcto={ok} ({motivo})")
	if ok:
		fallos += 1
	if FS_ENVENENADO == FS:
		print("[MAL] el fixture envenenado es idéntico al sano")
		fallos += 1
	print(f"\ncontrol negativo: {'FALLA' if fallos else 'OK'} ({fallos} discrepancias)")
	return 2 if fallos else 0


def main() -> None:
	ap = argparse.ArgumentParser(description="Multiturno de herramientas real (grader con respuesta esperada)")
	ap.add_argument("--port", type=int, default=30130)
	ap.add_argument("--vueltas", type=int, default=4)
	ap.add_argument("--json", default=None)
	ap.add_argument("--host", default="127.0.0.1")
	ap.add_argument("--control-negativo", action="store_true", help="prueba del grader, sin modelo")
	ap.add_argument("--dry-run", action="store_true", help="imprime fixtures y graders")
	args = ap.parse_args()

	if args.control_negativo:
		sys.exit(control_negativo())
	if args.dry_run:
		print(json.dumps({"fs": FS, "escenarios": [e[0] for e in ESCENARIOS]}, ensure_ascii=False, indent=1))
		return

	url = f"http://{args.host}:{args.port}/v1/chat/completions"
	res = [bucle(url, nombre, user, args.vueltas, grader, FS) for nombre, user, grader in ESCENARIOS]

	print(f"\n{'escenario':32s} {'pasos':>6s} {'responde':>9s} {'correcto':>9s}  motivo")
	for r in res:
		print(
			f"{r['escenario']:32s} {r['pasos']:6d} {('SÍ' if r['llego_a_respuesta'] else 'no'):>9s} "
			f"{('SÍ' if r['correcto'] else 'no'):>9s}  {r['motivo']}"
		)
	if args.json:
		with open(args.json, "w", encoding="utf-8") as fh:
			json.dump(res, fh, ensure_ascii=False, indent=1)
		print(f"\njson: {args.json}")
	if not all(r["correcto"] for r in res):
		sys.exit(1)


if __name__ == "__main__":
	main()
