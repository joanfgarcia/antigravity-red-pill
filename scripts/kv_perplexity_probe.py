#!/usr/bin/env python3
"""Perplejidad de la KV cache: f16 vs q8_0 vs q4_0 (RFC-HARNESS-001 · W2).

Corre `llama-perplexity` sobre el MISMO texto con la MISMA ventana y cambia sólo
el tipo de KV. La pregunta que responde: ¿cuánto se pierde al cuantizar la KV?

Salida: JSON con `{config, ppl, ppl_stderr, seconds, ok, error}` y una tabla en
stdout. Si q8_0 se separa de f16 más de un margen configurable, el diseño cambia
(f16 + ventana 12k) — por eso la comparación es explícita y no "a ojo".

Uso:
	python scripts/kv_perplexity_probe.py --model ~/.local/share/red-pill/models/MiMo-....gguf
	python scripts/kv_perplexity_probe.py --json out.json --text corpus.txt --ctx 16384
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Binario de llama.cpp: por entorno o por PATH. Un literal a la ruta del Operador
# ataba la sonda a su máquina (y `test_sound_of_silence` lo prohíbe con razón).
PERPLEXITY = os.getenv("LLAMA_PERPLEXITY") or shutil.which("llama-perplexity") or "llama-perplexity"
DEFAULT_MODEL = os.path.expanduser("~/.local/share/red-pill/models/MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf")

# Texto de calibración: prosa técnica en español + inglés, sin listas.
CORPUS = """El arnés es la parte del sistema que decide qué ve el modelo antes de responder.
Una identidad inyectada por el arnés no viaja como resultado de herramienta, sino como
contexto del sistema que no se persiste en el transcript; por eso sobrevive a la
compactación y no engorda el historial. La superficie de herramientas, en cambio, sí se
declara en cada petición, y su coste crece con el número de esquemas y con la longitud de
sus descripciones. Medir ese coste con un tokenizador real es distinto de estimarlo
dividiendo bytes entre cuatro, y la diferencia importa cuando la ventana es pequeña.
When the context window is scarce, every token spent on scaffolding is a token not spent
on the task. A nine-billion-parameter model on a consumer GPU can serve sixteen thousand
tokens comfortably if the key-value cache is stored in eight bits per element instead of
sixteen; the open question is whether that quantization costs measurable fidelity, and the
only honest way to answer it is to measure perplexity on the same corpus under both
configurations and compare. The cache grows linearly with sequence length and with the
number of layers, heads and head dimension, so the arithmetic is simple but unforgiving.
Un operador razonable prefiere un número medido a una intuición bien argumentada, y un
ingeniero honesto publica el número junto al método. El sandbox existe para que medir no
cueste caro: un agente aislado, su propia base vectorial, su propio escritorio, y ninguna
manera de tocar el mundo real salvo por la puerta que se abre a propósito. Cuando la puerta
está cerrada, el peor fallo posible es el que no se ve: una ruta que resuelve al directorio
del operador y escribe sin avisar. Por eso el aislamiento se demuestra en tres direcciones
—escritura, lectura y referencias— y no se acepta un verde que no pueda fallar."""

CONFIGS = [
	("f16", ["-ctk", "f16", "-ctv", "f16"]),
	("q8_0", ["-ctk", "q8_0", "-ctv", "q8_0"]),
	("q4_0", ["-ctk", "q4_0", "-ctv", "q4_0"]),
]


def run_config(model: str, ctx: int, text: Path, kv: list[str], ngl: str, timeout: int) -> dict:
	cmd = [PERPLEXITY, "-m", model, "-f", str(text), "-c", str(ctx), "-ngl", ngl, "-fa", "on", *[str(x) for x in kv]]
	t0 = time.time()
	try:
		out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
	except subprocess.TimeoutExpired:
		return {"ok": False, "error": f"timeout {timeout}s", "seconds": round(time.time() - t0, 1)}
	dt = time.time() - t0
	blob = (out.stdout or "") + (out.stderr or "")
	m = re.search(r"Final estimate: PPL\s*=\s*([0-9.]+)\s*\+/-\s*([0-9.]+)", blob) or re.search(r"PPL\s*=\s*([0-9.]+)", blob)
	if not m and "you need at least" in blob:
		return {"ok": False, "error": "corpus demasiado pequeño para perplexity (>=1024 tok)", "seconds": round(dt, 1)}
	if not m:
		tail = "\n".join(blob.strip().splitlines()[-6:])
		return {"ok": False, "error": f"sin PPL en la salida (rc={out.returncode}): {tail[-400:]}", "seconds": round(dt, 1)}
	return {
		"ok": True,
		"ppl": float(m.group(1)),
		"ppl_stderr": float(m.group(2)) if m.lastindex and m.lastindex >= 2 else None,
		"seconds": round(dt, 1),
	}


def main() -> int:
	ap = argparse.ArgumentParser(description="Perplejidad de KV (f16/q8_0/q4_0)")
	ap.add_argument("--model", default=DEFAULT_MODEL)
	ap.add_argument("--ctx", type=int, default=2048)
	ap.add_argument("--ngl", default="all")
	ap.add_argument("--text", default=None, help="corpus; por defecto el embebido")
	ap.add_argument("--timeout", type=int, default=900)
	ap.add_argument("--json", default=None)
	ap.add_argument("--max-delta", type=float, default=0.02, help="margen relativo q8_0 vs f16")
	args = ap.parse_args()

	if not Path(PERPLEXITY).is_file():
		print(f"[kv] no existe {PERPLEXITY}", file=sys.stderr)
		return 3
	if not Path(args.model).is_file():
		print(f"[kv] no existe el modelo {args.model}", file=sys.stderr)
		return 3

	if args.text:
		text = Path(args.text)
	else:
		text = Path(tempfile.mkdtemp(prefix="kvppl-")) / "corpus.txt"
		# llama-perplexity exige >= 1024 tokens y trabaja en trozos de `ctx`:
		# se repite el corpus hasta tener ~4x la ventana (en tokens ≈ chars/4).
		need_chars = args.ctx * 4 * 4
		blob = CORPUS
		while len(blob) < need_chars:
			blob += "\n\n" + CORPUS
		text.write_text(blob, encoding="utf-8")
		print(f"[kv] corpus: {len(blob):,} chars (~{len(blob) // 4:,} tok) para ctx={args.ctx}")

	rows = []
	for name, kv in CONFIGS:
		print(f"[kv] {name} …", flush=True)
		res = run_config(args.model, args.ctx, text, kv, args.ngl, args.timeout)
		res["config"] = name
		res["kv"] = " ".join(kv)
		rows.append(res)
		print(f"[kv] {name}: {res.get('ppl') or res.get('error')}", flush=True)

	ok = {r["config"]: r for r in rows if r["ok"]}
	veredicto = "no medido"
	if "f16" in ok and "q8_0" in ok:
		delta = abs(ok["q8_0"]["ppl"] - ok["f16"]["ppl"]) / ok["f16"]["ppl"]
		veredicto = f"q8_0 vs f16: {delta * 100:.2f}% ({'dentro del margen' if delta <= args.max_delta else 'FUERA del margen'})"

	print("\nconfig   ppl        stderr    s")
	for r in rows:
		if r["ok"]:
			print(f"{r['config']:8s} {r['ppl']:<10.4f} {str(r.get('ppl_stderr')):<9} {r['seconds']}")
		else:
			print(f"{r['config']:8s} ERROR: {r['error'][:100]}")
	print(f"\n{veredicto}")

	if args.json:
		Path(args.json).write_text(
			json.dumps({"model": args.model, "ctx": args.ctx, "veredicto": veredicto, "rows": rows}, ensure_ascii=False, indent=1),
			encoding="utf-8",
		)
		print(f"json: {args.json}")
	return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
	sys.exit(main())
