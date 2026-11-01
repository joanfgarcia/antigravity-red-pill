#!/usr/bin/env python3
"""Cata de notas: muestra reproducible + métricas automáticas contra la fuente.

Muestrea N notas de una ronda y, para cada una, saca la nota y la polaroid de la
que salió (`distill_ref`), con cuatro comprobaciones que NO dependen de mi gusto:

	anclas_fuera   rutas/hashes/números que aparecen en la NOTA y NO en la polaroid
				→ candidato a invención (el dato no estaba en el material)
	solape         Jaccard de palabras (sin stopwords) nota↔polaroid
				→ muy bajo = nota que no sale del material; muy alto = copia literal
	arranque       empieza a media frase ("y ", "pero ", "que ", minúscula)
	deixis         pronombre sin referente al principio ("Esto", "Eso", "Ello")

La muestra va con semilla para que se pueda repetir y discutir la misma cata.

Uso:
	python scripts/memento_cata.py --n 25 --seed 20261030 --out /tmp/cata.md
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FM = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)
ANCLA = re.compile(r"`[^`\n]{2,80}`|/[\w./-]{6,}|[0-9a-f]{7,40}|\b\d{3,}\b|\b[a-z_]{6,}\(")
STOP = set(
	"de la que el en y a los del se las por un para con no una su al lo como mas pero sus le ya o este si porque "
	"esta entre cuando muy sin sobre tambien me hasta hay donde quien desde todo nos durante todos uno les ni contra "
	"otros ese eso ante ellos e esto mi antes algunos que unos yo otro otras otra el tanto esa estos mucho quienes "
	"nada muchos cual poco ella estar estas algunas algo nosotros mi mis tu te ti tus ellas nosotras vosostros vosostras "
	"os mio mia mios mias tuyo tuya tuyos tuyas suyo suya suyos suyas nuestro nuestra nuestros nuestras vuestro vuestra "
	"vuestros vuestras esos esas estoy estas esta estamos estais estan este estes estemos esteis esten".split()
)
MEDIA_FRASE = re.compile(r"^(y |pero |que |aunque |ademas |además |pues |entonces )", re.I)
PRONOMBRE = re.compile(r"^(esto|eso|ello|aquello|este|esta|dicho|dicha)\b", re.I)


def _fm(text: str):
	m = FM.match(text)
	if not m:
		return {}, text
	cab = {}
	for line in m.group(1).splitlines():
		if ":" in line:
			k, _, v = line.partition(":")
			cab[k.strip()] = v.strip()
	return cab, m.group(2).strip()


def _palabras(t: str) -> set:
	return {w for w in re.findall(r"[a-záéíóúñ_]{3,}", t.lower()) if w not in STOP}


def _anclas(t: str) -> set:
	return set(ANCLA.findall(t))


def main() -> None:
	ap = argparse.ArgumentParser(description="Cata de notas con métricas contra la fuente")
	ap.add_argument("--n", type=int, default=25)
	ap.add_argument("--seed", type=int, default=20261030)
	ap.add_argument("--engine", default="k2_horizon_7b", help="motor de las notas a muestrear")
	ap.add_argument("--root", default=None)
	ap.add_argument("--out", default="/tmp/cata.md")
	args = ap.parse_args()

	if args.root:
		root = Path(args.root)
	else:
		from red_pill.memento import get_memento_root

		root = get_memento_root()

	pool: List[Dict[str, Any]] = []
	for f in root.glob("*/*/*/annotate/*.md"):
		cab, cuerpo = _fm(f.read_text(encoding="utf-8", errors="ignore"))
		if args.engine and cab.get("engine") != args.engine:
			continue
		pool.append({"path": f, "cab": cab, "texto": cuerpo})
	if not pool:
		print("sin notas de ese motor", file=sys.stderr)
		return
	pool.sort(key=lambda r: str(r["path"]))
	random.Random(args.seed).shuffle(pool)
	muestra = pool[: args.n]

	filas = []
	for item in muestra:
		cab, texto = item["cab"], item["texto"]
		p = item["path"]
		ses_dir = p.parents[1]
		# La FUENTE REAL de una nota son las líneas del RAW que declara
		# (`source_lines`), no la polaroid: el pase lee el raw, y `distill_ref` es
		# sólo linaje. Comparar contra la polaroid marca como "inventado" lo que sí
		# estaba en el material (error detectado en la primera pasada de la cata).
		fuente = ""
		sl = cab.get("source_lines", "")
		m = re.search(r"#l(\d+)-(\d+)", sl)
		index = ses_dir / "memento" / "index.md"
		if m and index.exists():
			lineas = index.read_text(encoding="utf-8", errors="ignore").splitlines()
			a, b = int(m.group(1)), int(m.group(2))
			fuente = "\n".join(lineas[max(0, a - 1) : b])
		if not fuente:
			ref = cab.get("distill_ref", "")
			for cand in (root / ref, ses_dir / ref):
				if ref and cand.exists():
					fuente = _fm(cand.read_text(encoding="utf-8", errors="ignore"))[1]
					break
		a_nota, a_fuente = _anclas(texto), _anclas(fuente)
		fuera = sorted(a_nota - a_fuente)
		solape = 0.0
		if fuente:
			pn, pf = _palabras(texto), _palabras(fuente)
			solape = len(pn & pf) / max(len(pn | pf), 1)
		filas.append(
			{
				"sesion": p.parents[1].name,
				"fichero": p.name,
				"titulo": cab.get("title", ""),
				"significance": cab.get("significance", ""),
				"texto": texto,
				"fuente": fuente[:1200],
				"anclas_fuera": fuera,
				"solape": round(solape, 2),
				"media_frase": bool(MEDIA_FRASE.match(texto)),
				"pronombre": bool(PRONOMBRE.match(texto)),
				"chars": len(texto),
			}
		)

	md = [f"# Cata de {len(filas)} notas · motor {args.engine} · semilla {args.seed}\n"]
	for i, f in enumerate(filas, 1):
		md.append(f"## {i}. {f['titulo']}")
		md.append(
			f"- sesión `{f['sesion'][-24:]}` · sig **{f['significance']}** · {f['chars']} chars · "
			f"solape {f['solape']} · media_frase={'SÍ' if f['media_frase'] else 'no'} · "
			f"pronombre={'SÍ' if f['pronombre'] else 'no'}"
		)
		if f["anclas_fuera"]:
			md.append(f"- **anclas fuera de la fuente**: {', '.join(f['anclas_fuera'][:6])}")
		md.append(f"\n> {f['texto']}\n")
		md.append(f"<details><summary>fuente real ({sl or 'polaroid'})</summary>\n\n{f['fuente']}\n</details>\n")

	resumen = {
		"n": len(filas),
		"media_frase": sum(f["media_frase"] for f in filas),
		"pronombre": sum(f["pronombre"] for f in filas),
		"con_anclas_fuera": sum(1 for f in filas if f["anclas_fuera"]),
		"anclas_fuera_total": sum(len(f["anclas_fuera"]) for f in filas),
		"solape_medio": round(sum(f["solape"] for f in filas) / len(filas), 2),
		"chars_medio": round(sum(f["chars"] for f in filas) / len(filas)),
	}
	md.insert(1, "```\n" + json.dumps(resumen, indent=1, ensure_ascii=False) + "\n```\n")
	Path(args.out).write_text("\n".join(md), encoding="utf-8")
	print(json.dumps(resumen, indent=1, ensure_ascii=False))
	print(f"\ncata: {args.out}")


if __name__ == "__main__":
	main()
