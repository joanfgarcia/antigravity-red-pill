#!/usr/bin/env python3
"""¿Aguanta la calidad a ventana llena? Needle con KV de 2 bits.

`kv_ceiling.py` mide lo que el servidor **acepta**; esto mide lo que el modelo
**lee**. Sirve para decidir si `pq2_0m` (8,8 MiB/1k en el 27B; 4,4 en el 9B) es
ventana utilizable o sólo un número bonito.

Diseño: un dato único (código de 6 dígitos) sembrado en una posición conocida de
un texto de relleno sintético y reproducible, pregunta al final, verificación por
JSON. Una sesión por tamaño, semilla distinta por tamaño para no premiar memoria.

Uso:
	PYTHONPATH=src .venv/bin/python scripts/needle_window.py \
		--profile bonsai_25_27b --kv pq2_0m --sizes 25000,50000,75000,100000

Salida: `bench/window/<fecha>-needle-<perfil>-<kv>.md` + `.jsonl`
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY = "CLAVE-7F3A"


def build(target_tokens: int, seed: int) -> tuple[str, str]:
	"""Devuelve (texto con el dato, código esperado). ~4 chars por token."""
	rng = random.Random(seed)
	code = f"{rng.randint(100000, 999999)}"
	filler = (
		"En la reunión se revisaron los sistemas habituales y se acordó continuar con el plan previsto sin cambios."
	)
	n = max(12, (target_tokens * 4) // (len(filler) + 1))
	lines = [filler] * n
	lines.insert(int(n * 0.62), f"DATO ÚNICO: {KEY} -> el código de desbloqueo del cofre es {code}.")
	question = (
		f'En el texto hay un dato único que empieza por "{KEY}". '
		f'Devuelve SOLO un JSON válido: {{"clave": "{KEY}", "codigo": "<el código de 6 dígitos>"}}'
	)
	return "\n".join(lines) + "\n\n" + question, code


def parse(raw: str) -> dict:
	idx = raw.find("{")
	if idx < 0:
		return {"valid": False, "reason": "no JSON", "raw_tail": raw[-120:]}
	try:
		obj, _ = json.JSONDecoder().raw_decode(raw[idx:])
	except Exception:
		return {"valid": False, "reason": "JSON roto", "raw_tail": raw[-120:]}
	return {"valid": True, "got": str(obj.get("codigo", "")), "clave": obj.get("clave")}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--profile", required=True)
	ap.add_argument("--kv", default="pq2_0m")
	ap.add_argument("--ctx", type=int, default=0, help="n_ctx del servidor (0 = techo del mayor tamaño + margen)")
	ap.add_argument("--sizes", default="25000,50000,75000,100000")
	ap.add_argument("--out", default=str(REPO / "bench" / "window"))
	args = ap.parse_args()

	from red_pill.inference.runtime_server import RuntimeServer

	sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
	ctx = args.ctx or int(max(sizes) * 1.10) + 2048
	out_dir = Path(args.out)
	out_dir.mkdir(parents=True, exist_ok=True)
	stamp = time.strftime("%Y-%m-%d")
	base = out_dir / f"{stamp}-needle-{args.profile}-{args.kv}-ctx{ctx}"

	rows = []
	md = [f"# Needle a ventana llena — {args.profile} · KV `{args.kv}` · ctx {ctx}", ""]
	server = RuntimeServer(args.profile, ctx=ctx, kv_type=args.kv).start()
	try:
		for i, size in enumerate(sizes):
			text, expected = build(size, seed=1000 + i)
			t0 = time.time()
			resp = server.chat(
				[{"role": "user", "content": text}],
				max_tokens=64,
				temperature=0.0,
				top_p=1.0,
				top_k=1,
				min_p=0.0,
				chat_template_kwargs={"enable_thinking": False},
			)
			elapsed = time.time() - t0
			raw = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
			got = parse(raw)
			ok = got.get("valid") and got.get("got") == expected
			usage = resp.get("usage") or {}
			row = {
				"profile": args.profile,
				"kv": args.kv,
				"ctx": ctx,
				"target_tokens": size,
				"chars": len(text),
				"prompt_tokens": usage.get("prompt_tokens"),
				"ok": bool(ok),
				"expected": expected,
				"got": got.get("got"),
				"latency_s": round(elapsed, 1),
			}
			rows.append(row)
			print(
				f"  {size // 1000:>4}k tokens ({len(text) // 1000}k chars, prompt {usage.get('prompt_tokens')}): "
				f"{'✓' if ok else '✗'} {elapsed:.1f}s",
				flush=True,
			)
			md.append(f"- {size // 1000}k → **{'✓' if ok else '✗'}** · {elapsed:.1f}s · prompt {usage.get('prompt_tokens')} tokens")
	finally:
		server.stop()

	fails = sum(1 for r in rows if not r["ok"])
	md += ["", f"**{len(rows) - fails}/{len(rows)}** recuperaciones correctas."]
	base.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
	base.with_suffix(".jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
	print(f"-> {base}.md")
	return 0 if fails == 0 else 1


if __name__ == "__main__":
	raise SystemExit(main())
