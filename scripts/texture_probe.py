#!/usr/bin/env python3
"""texture_probe — prueba de textura sobre fragmentos REALES del archivo.

Protocolo de casa (docs/MODELS/TEXTURE_2026-10-29.md): mismo prompt para todos
los candidatos, misma temperatura, ciego A/B con semilla fija, y se cuentan
cosas objetivas: JSON válido, vallas markdown, primera/tercera persona, deixis
de segunda persona, relics verbatim y **escenas inventadas** (atmósfera que no
estaba en la fuente).

Dos modos:
	# 1) destilar con un modelo (una vez por candidato, mismo backend HTTP)
	python scripts/texture_probe.py --model bonsai_2_27b --port 30150 --out /tmp/bonsai.jsonl

	# 2) ciego A/B sobre dos salidas
	python scripts/texture_probe.py --render /tmp/bonsai.jsonl /tmp/mimo.jsonl \
	    --out docs/BENCHMARKS/2026-11-16-TEXTURE_MIMO_VS_BONSAI.md --seed 20261116

Los fragmentos se extraen del archivo de Memento (una sesión por mes, tomando
un intercambio a 1/4, 1/2 y 3/4 de la conversación). Sólo lectura.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Contadores de deixis: los mismos del battle de destilado, no una copia nueva.
from model_battle import BAD_2ND, SECOND, THIRD  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PROMPT_FILE = REPO / "src" / "red_pill" / "metabolism" / "prompts" / "distiller_v3_voice.txt"
ARCHIVE = Path.home() / ".local" / "share" / "red-pill" / "memento"

# Atmósfera que la fuente no trae: si aparece en el resumen, se ha pintado color.
_ATMOSFERA = ("luz", "aire", "silencio", "olor", "calor", "habitación", "ventana", "cielo", "sol", "sombra", "eco")


def extraer_fragmentos(meses: list[str], por_mes: int = 3) -> list[dict]:
	"""Un intercambio real por posición (1/4, 1/2, 3/4) de cada sesión elegida.

	Se descartan los intercambios dominados por ruido de herramientas
	(`[TOOL: …]`): lo que se mide es la voz al destilar, no el log.
	"""
	frags: list[dict] = []
	for mes in meses:
		base = ARCHIVE / mes / "opencode"
		if not base.is_dir():
			continue
		cogidos = 0
		for ses in sorted(p for p in base.iterdir() if p.is_dir())[:6]:
			texto = "\n\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in sorted(ses.rglob("*.md")))
			bloques = re.split(r"^## .*? — (Usuario|Asistente)\s*$", texto, flags=re.M)
			turnos = [(bloques[i], bloques[i + 1]) for i in range(1, len(bloques) - 1, 2)]
			turnos = [(r, c.strip()) for r, c in turnos if len(c.strip()) > 200]
			if len(turnos) < 4:
				continue
			for pos in (0.25, 0.5, 0.75):
				if cogidos >= por_mes:
					break
				i = int(len(turnos) * pos)
				rol, cuerpo = turnos[i]
				j = i + 1 if i + 1 < len(turnos) else i - 1
				otro_rol, otro = turnos[j]
				user, asst = (otro, cuerpo) if rol.lower().startswith("asist") else (cuerpo, otro)
				# ruido de herramientas: fuera
				if asst.count("[TOOL:") > max(2, len(asst.splitlines()) // 4):
					continue
				frags.append(
					{
						"id": f"{mes}-{ses.name[-6:]}-{int(pos * 100)}",
						"source": f"{mes}/{ses.name}",
						"data": f"USER: {user[:2500]}\nASSISTANT: {asst[:2500]}",
					}
				)
				cogidos += 1
			if cogidos >= por_mes:
				break
	return frags


def _score(raw: str, data: str) -> dict:
	"""Métricas del protocolo de textura (hechos, no impresiones)."""
	m = re.search(r"\{[\s\S]*\}", raw or "")
	obj = None
	if m:
		try:
			obj = json.loads(m.group(0))
		except ValueError:
			obj = None
	resumen = str((obj or {}).get("summary", "")) if isinstance(obj, dict) else ""
	low = resumen.lower()
	fuente = data.lower()
	relics = (obj or {}).get("relics", []) if isinstance(obj, dict) else []
	verbatim = [r for r in relics if str(r).lower().strip().strip('"') in fuente]
	inventadas = [w for w in _ATMOSFERA if w in low and w not in fuente]
	return {
		"json_valid": isinstance(obj, dict),
		"fences": "```" in (raw or ""),
		"summary": resumen,
		"relics": len(relics),
		"relics_verbatim": len(verbatim),
		"first_person": sum(low.count(t) for t in SECOND),
		"third_person": sum(low.count(t) for t in THIRD),
		"bad_deixis": [t for t in BAD_2ND if t in low],
		"invented": inventadas,
	}


def _post(port: int, payload: dict) -> dict:
	req = urllib.request.Request(
		f"http://127.0.0.1:{port}/v1/chat/completions",
		data=json.dumps(payload).encode(),
		headers={"Content-Type": "application/json"},
	)
	return json.loads(urllib.request.urlopen(req, timeout=900).read())


def destilar(model: str, port: int, frags: list[dict], out: Path, max_tokens: int) -> None:
	prompt = PROMPT_FILE.read_text(encoding="utf-8")
	prompt = prompt.replace("{agent_name}", "Aleth").replace("{operator_name}", "Joan")
	rows = []
	for frag in frags:
		t0 = time.time()
		r = _post(
			port,
			{
				"model": model,
				"messages": [{"role": "system", "content": prompt}, {"role": "user", "content": "DATA:\n" + frag["data"]}],
				"temperature": 0.3,
				"max_tokens": max_tokens,
			},
		)
		raw = r["choices"][0]["message"].get("content") or ""
		row = {"model": model, "id": frag["id"], "source": frag["source"], "latency_s": round(time.time() - t0, 2), "raw": raw}
		row.update(_score(raw, frag["data"]))
		rows.append(row)
		print(f"  [{model}] {frag['id']}: json={row['json_valid']} 3rd={row['third_person']} inv={len(row['invented'])} {row['latency_s']}s", flush=True)
	out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
	print(f"→ {out} ({len(rows)} filas)")


def render(a: Path, b: Path, out: Path, seed: int) -> None:
	def load(p: Path) -> tuple[str, dict]:
		rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
		return rows[0]["model"], {r["id"]: r for r in rows}

	ma, ra = load(a)
	mb, rb = load(b)
	ids = sorted(set(ra) & set(rb))
	rnd = random.Random(seed)
	lineas = [
		"# Prueba de textura — " + ma + " vs " + mb,
		"",
		"> Protocolo: docs/MODELS/TEXTURE_2026-10-29.md. Mismo prompt, `temperature 0.3`,",
		"> thinking apagado en ambos, ciego A/B barajado con semilla fija. Los pares van al",
		"> final: **la lectura ciega la firma el Operador**, aquí solo van los hechos.",
		"",
		"## Objetivo",
		"",
		"| Modelo | JSON | Vallas | 3ª persona | Deixis mala | Escenas inventadas | Relics verbatim | s/frag |",
		"| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |",
	]
	for m, r in ((ma, ra), (mb, rb)):
		n = max(len(r), 1)
		lineas.append(
			"| {} | {}/{} | {} | {} | {} | {} | {}/{} | {:.1f} |".format(
				m,
				sum(x["json_valid"] for x in r.values()),
				n,
				sum(x["fences"] for x in r.values()),
				sum(x["third_person"] for x in r.values()),
				sum(len(x["bad_deixis"]) for x in r.values()),
				sum(len(x["invented"]) for x in r.values()),
				sum(x["relics_verbatim"] for x in r.values()),
				sum(x["relics"] for x in r.values()),
				sum(x["latency_s"] for x in r.values()) / n,
			)
		)
	lineas += ["", "## Pares ciegos", ""]
	mapa = []
	for i, fid in enumerate(ids, 1):
		orden = [("A", ma, ra[fid]), ("B", mb, rb[fid])]
		rnd.shuffle(orden)
		mapa.append({"par": i, "A": orden[0][1], "B": orden[1][1]})
		for etiqueta, modelo, row in orden:
			lineas += [f"### Par {i} — {etiqueta}", "", row["summary"] or f"(sin JSON) {row['raw'][:400]}", ""]
	out.write_text("\n".join(lineas), encoding="utf-8")
	out.with_suffix(".map.json").write_text(json.dumps(mapa, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"→ {out} (+ mapa en {out.with_suffix('.map.json').name})")


def main() -> None:
	ap = argparse.ArgumentParser(description="Prueba de textura sobre fragmentos reales.")
	ap.add_argument("--model")
	ap.add_argument("--port", type=int, default=30150)
	ap.add_argument("--months", default="2026-07,2026-08,2026-09")
	ap.add_argument("--max-tokens", type=int, default=600)
	ap.add_argument("--out", required=True)
	ap.add_argument("--render", nargs=2, metavar=("A.jsonl", "B.jsonl"))
	ap.add_argument("--seed", type=int, default=20261116)
	args = ap.parse_args()

	if args.render:
		render(Path(args.render[0]), Path(args.render[1]), Path(args.out), args.seed)
		return
	frags = extraer_fragmentos([m.strip() for m in args.months.split(",") if m.strip()])
	if not frags:
		raise SystemExit("sin fragmentos: revisa el archivo de Memento")
	print(f"{len(frags)} fragmentos reales de {args.months}", flush=True)
	destilar(args.model or "local", args.port, frags, Path(args.out), args.max_tokens)


if __name__ == "__main__":
	main()
