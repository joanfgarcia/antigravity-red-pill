"""¿Cuántos turnos atrás conserva el hilo Dokimé?

Para cada distancia d se abre una sesión NUEVA: se planta un código de 4 cifras
al principio, se dan d-1 turnos de trabajo y se pregunta por el código en el
turno d+1. Aislamiento por distancia: no hay repetición de la pregunta que pueda
reforzar el recuerdo, y cada sesión es independiente.

El código es ALEATORIO en cada sesión: en la sonda anterior el número estaba
escrito en `drift_probe.py` y Dokimé lo encontró leyendo el fichero con sus
herramientas. Aquí no existe en disco, así que "acertar" sólo puede significar
recordarlo (o inventarlo, que también se detecta).

Uso:
	python scripts/window_probe.py [--model spark] [--dists 1,2,3,4,6,8]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

CONTAINER = "dokime"
WORKDIR = "/srv/dokime/workspace"
OUT_DIR = Path("bench/window")

FILLERS = [
	"¿Qué diferencia hay entre un test unitario y uno de integración? Dos frases.",
	"Escribe una función Python que invierta una cadena sin usar `[::-1]`.",
	"¿Qué es una condición de carrera? Una frase.",
	"Si un proceso se queda dormido esperando un socket, ¿qué estado muestra? Una frase.",
	"Explica qué hace `git merge --squash` en dos frases.",
	"¿Qué es un lock optimista y cuándo falla? Dos frases.",
	"¿Por qué un test puede pasar solo y fallar en la suite? Da dos causas.",
	"Define idempotencia con un ejemplo de una línea.",
	"¿Qué mide la perplejidad de un modelo de lenguaje? Una frase.",
	"¿Qué es un KV cache en inferencia? Dos frases.",
	"¿Por qué cuantizar el KV cache degrada más que cuantizar pesos? Dos frases.",
	"Enumera tres formas de medir que un agente mantiene su identidad.",
]

ASK = (
	"¿Cuál fue el código de 4 cifras que te di al principio de esta conversación? "
	"Responde SÓLO el número. Si no lo sabes con certeza, escribe exactamente: NO LO SÉ."
)


def run_turn(session: str, model: str, prompt: str, timeout: int = 300) -> tuple[str, float]:
	inner = (
		f"timeout {timeout} pi --session-id {session} -p {json.dumps(prompt, ensure_ascii=False)} --provider local --model {model} --mode text 2>&1"
	)
	t0 = time.time()
	out = subprocess.run(
		["podman", "exec", "-w", WORKDIR, CONTAINER, "sh", "-lc", inner],
		capture_output=True,
		text=True,
		timeout=timeout + 60,
	)
	lines = [ln for ln in (out.stdout or "").strip().splitlines() if not ln.startswith("Warning: No project")]
	return "\n".join(lines).strip(), time.time() - t0


def classify(answer: str, code: str) -> str:
	"""recordado · no_lo_sabe · inventado · silencio."""
	low = answer.lower().strip()
	if not low:
		return "silencio"
	if code in answer:
		# El código es aleatorio y no está en disco: si aparece, es recuerdo.
		return "recordado"
	if re.search(r"no lo s[eé]|no lo recuerdo|no puedo recordar|no tengo (ese|el) dato", low):
		return "no_lo_sabe"
	return "inventado"


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--model", default="spark")
	ap.add_argument("--dists", default="1,2,3,4,6,8")
	args = ap.parse_args()

	dists = [int(x) for x in args.dists.split(",") if x.strip()]
	stamp = f"{datetime.now():%Y%m%d-%H%M}"
	OUT_DIR.mkdir(parents=True, exist_ok=True)
	rows: list[dict[str, object]] = []

	for d in dists:
		code = str(random.randint(1000, 9999))
		session = f"win-{d}-{stamp}"
		print(f"\n── distancia {d} turno(s) · sesión {session} · código {code} ──")
		plant = f"Guarda este código de 4 cifras: {code}. No lo repitas ahora, sólo guárdalo."
		txt, secs = run_turn(session, args.model, plant)
		print(f"  [planta] {secs:4.1f}s  {txt[:60]}")
		for i in range(2, d + 1):
			filler = FILLERS[(i - 2) % len(FILLERS)]
			txt, secs = run_turn(session, args.model, filler)
			print(f"  [relleno {i}] {secs:4.1f}s  {txt[:50]}")
		answer, secs = run_turn(session, args.model, ASK)
		verdict = classify(answer, code)
		print(f"  [pregunta turno {d + 1}] {verdict.upper()} · {answer[:70]}")
		rows.append(
			{
				"distance": d,
				"session": session,
				"code": code,
				"answer": answer,
				"verdict": verdict,
				"seconds": round(secs, 1),
			}
		)

	out = OUT_DIR / f"window-{stamp}.json"
	out.write_text(json.dumps({"model": args.model, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

	print("\n── resumen ──")
	for r in rows:
		print(f"  {r['distance']:>2} turno(s): {r['verdict']:<12} {str(r['answer'])[:50]}")
	print(f"\ncrudo: {out}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
