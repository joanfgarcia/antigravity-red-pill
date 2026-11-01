#!/usr/bin/env python3
"""Banco de pruebas: ¿la organización documental sirve a un modelo pequeño?

QUÉ MIDE (y qué no)
-------------------
No mide la calidad del modelo. Mide si **la estructura documental** (índices
curados + documentos acotados) le permite trabajar: enrutar con el índice,
resumir sin inventar, y no confabular contradicciones.

Para que dos modelos se puedan CONTRASTAR, la suite está **fijada aquí**
(`SUITE`), con los mismos ficheros y las mismas preguntas. Un test con preguntas
distintas no es comparable.

LOS CINCO CASOS (diseñados el 2026-10-29 con granite_8b)
---------------------------------------------------------
    T1  índice como puerta         ~3 KB    ¿enruta al documento y sección correctos?
    T2  documento de trabajo      ~11 KB    ¿resume fiel y acierta la decisión abierta?
    T3  documento grande          ~74 KB    ¿cabe? (con 10K de contexto: NO)
    T3b solo el TOC del grande    ~1,8 KB   ¿basta un índice de secciones crudo?
    T4  control negativo          ~14 KB    ¿confabula una contradicción que no existe?

Resultado de referencia (granite_8b, contexto 10.240 tok, 2026-10-29):
    T1  OK §4.2 + §4.4            5,6 s · 1.038 tok
    T2  OK resumen fiel + D-01    6,0 s · 3.545 tok
    T3  FALLA: HTTP 500           22.964 tok > 10.240 de contexto
    T3b dice §4.3 (es §4.4)       el índice crudo induce error de proximidad
    T4  "NO" en 8 tokens          acierta por defecto; NO demuestra detección

Uso
---
    python3 planner/tools/doc_read_bench.py --suite
    python3 planner/tools/doc_read_bench.py --suite --model k2-horizon-3.7b
    python3 planner/tools/doc_read_bench.py --files a.md --question "…"
    python3 planner/tools/doc_read_bench.py --suite --json     # comparable

El endpoint tiene que estar sirviendo el modelo (OpenAI-compatible). Por defecto
`http://127.0.0.1:8760/v1/chat/completions` (redpill-llm del daemon).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_API = "http://127.0.0.1:8760/v1/chat/completions"
DEFAULT_MODEL = "granite_8b"
# Tope defensivo de caracteres enviados (el contexto real lo decide el servidor).
MAX_CTX_CHARS = 96_000

DESK = Path(__file__).resolve().parents[2]
INTEROP = DESK / "planner" / "design" / "agent_interop"
TOC_001_SRC = INTEROP / "RFC_INTEROP_001_BUS_MENSAJERIA.md"

# ── La suite, fijada: mismas preguntas para que el contraste valga ------------
SUITE = [
	{
		"id": "T1",
		"what": "indice como puerta (enruta bien?)",
		"files": [str(INTEROP / "INDEX.md")],
		"question": "Si quiero implementar la entrega de mensajes entre arneses, ¿qué documento y qué secciones concretas debo leer? Sé breve.",
		"expect": "RFC_INTEROP_001 + 4.2 (modelo de datos) + 4.4 (flujo de entrega)",
	},
	{
		"id": "T2",
		"what": "documento de trabajo (resume sin inventar?)",
		"files": [str(INTEROP / "RFC_INTEROP_002_RELEVO_PROGRAMADO.md")],
		"question": "Resume los 3 puntos clave del documento y dime UNA decisión abierta con su id.",
		"expect": "despertadores / presupuesto / enrutado por coste + D-01",
	},
	{
		"id": "T3",
		"what": "documento grande (cabe?)",
		"files": [str(INTEROP / "RFC_INTEROP_001_BUS_MENSAJERIA.md")],
		"question": "Resume los 3 puntos clave del documento y dime UNA decisión abierta con su id.",
		"expect": "con ~10K de contexto NO cabe (22964 tok); la respuesta util es un error claro",
	},
	{
		"id": "T3b",
		"what": "solo el TOC del grande (basta un indice crudo?)",
		"files": "TOC",
		"question": "Este es el índice de secciones de un RFC. Si quiero entender el modelo de datos y el flujo de entrega, ¿qué secciones debo leer?",
		"expect": "4.2 y 4.4. Un TOC crudo suele errar por proximidad (dice 4.3 = API).",
	},
	{
		"id": "T4",
		"what": "control negativo (confabula contradicciones?)",
		"files": [str(INTEROP / "INDEX.md"), str(INTEROP / "RFC_INTEROP_002_RELEVO_PROGRAMADO.md")],
		"question": "¿Hay alguna CONTRADICCIÓN entre estos dos documentos? Responde exactamente SI o NO en la primera palabra.",
		"expect": "NO. Ojo: NO siempre acierta en un control negativo; sin un caso POSITIVO no prueba deteccion.",
	},
]


def _toc(path: Path) -> str:
	"""Indice de secciones (solo encabezados) de un documento."""
	return "\n".join(
		ln for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.startswith("## ") or ln.startswith("### ")
	)


def _resolve(files):
	if files == "TOC":
		tmp = Path("/tmp") / "doc_read_bench_toc001.md"
		tmp.write_text(_toc(TOC_001_SRC), encoding="utf-8")
		return [tmp]
	return [Path(f) for f in files]


def build_prompt(paths, question: str) -> str:
	parts = []
	for p in paths:
		text = p.read_text(encoding="utf-8", errors="ignore")
		if len(text) > MAX_CTX_CHARS:
			text = text[:MAX_CTX_CHARS]
		parts.append(f"<<<DOCUMENTO: {p.name}>>>\n{text}\n<<<FIN: {p.name}>>>")
	return (
		"Responde SOLO con lo que aparezca en los documentos de abajo. No inventes.\n\n"
		+ "\n\n".join(parts)
		+ f"\n\nPREGUNTA: {question}\n"
	)


def run(api: str, model: str, paths, question: str, max_tokens: int = 1400) -> dict:
	prompt = build_prompt(paths, question)
	t0 = time.time()
	req = urllib.request.Request(
		api,
		data=json.dumps(
			{
				"model": model,
				"messages": [{"role": "user", "content": prompt}],
				"temperature": 0.0,
				"max_tokens": max_tokens,
			}
		).encode(),
		headers={"Content-Type": "application/json"},
	)
	try:
		with urllib.request.urlopen(req, timeout=280) as resp:
			data = json.loads(resp.read())
	except Exception as e:
		return {"error": str(e), "prompt_chars": len(prompt), "elapsed_s": round(time.time() - t0, 1)}
	usage = data.get("usage") or {}
	text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
	return {
		"prompt_chars": len(prompt),
		"out_chars": len(text),
		"tokens_prompt": usage.get("prompt_tokens"),
		"tokens_out": usage.get("completion_tokens"),
		"elapsed_s": round(time.time() - t0, 1),
		"answer": text,
	}


def main() -> int:
	ap = argparse.ArgumentParser(description="Banco de pruebas de asimilacion documental.")
	ap.add_argument("--suite", action="store_true", help="Ejecuta los 5 casos fijados (comparable entre modelos).")
	ap.add_argument("--model", default=DEFAULT_MODEL)
	ap.add_argument("--api", default=DEFAULT_API)
	ap.add_argument("--files", nargs="*", help="Uso libre: ficheros a enviar.")
	ap.add_argument("--question", help="Uso libre: pregunta.")
	ap.add_argument("--json", action="store_true", help="Salida JSON (para contrastar).")
	ap.add_argument("--max-tokens", type=int, default=1400, help="Tope de salida. Los modelos de RAZONAMIENTO gastan parte pensando: con un tope bajo devuelven contenido vacio y el test falla por una razon falsa.")
	args = ap.parse_args()

	if not args.suite and not (args.files and args.question):
		ap.print_help()
		return 2

	results = []
	cases = SUITE if args.suite else [{"id": "custom", "what": "libre", "files": args.files, "question": args.question, "expect": ""}]
	for case in cases:
		paths = _resolve(case["files"])
		out = run(args.api, args.model, paths, case["question"], args.max_tokens)
		out.update({"id": case["id"], "what": case.get("what"), "expect": case.get("expect")})
		results.append(out)
		if not args.json:
			print(f"\n=== {case['id']} - {case.get('what', '')}")
			if "error" in out:
				print(f"    ERROR: {out['error']} ({out['prompt_chars']:,} ch)")
			else:
				print(f"    {out['prompt_chars']:,} ch | tok {out['tokens_prompt']}/{out['tokens_out']} | {out['elapsed_s']}s")
				print("    " + out["answer"].replace("\n", "\n    ")[:900])
			if case.get("expect"):
				print(f"    (esperado: {case['expect']})")

	if args.json:
		print(json.dumps({"model": args.model, "api": args.api, "results": results}, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	sys.exit(main())
