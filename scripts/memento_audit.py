#!/usr/bin/env python3
"""Auditoría READ-ONLY del árbol Memento: busca patrones que quisiéramos corregir.

No toca nada. No llama al LLM. Lee `distill/*.md` y `annotate/*.md` y emite un
JSONL (una fila por sesión) + un resumen por patrón.

Por qué determinista y no un LLM (decisión 2026-10-30): un listado de trabajo que
cambia de una pasada a otra no sirve para decidir a qué dedicar una noche. Los
patrones de aquí son medibles con regex y estructura; el LLM (K2) se reserva para
ADJUDICAR los casos dudosos de una segunda pasada, no para inventariarlos.

Patrones:
	deixis            "el archivo especificado", "ese archivo", "dicho X"… (un
					recuerdo que no se puede usar para volver al origen)
	tono_inventado    "con calma", "con ironía", "el tono es", "emocionalmente"…
					(la manera de decir algo que NO está en el fragmento)
	tercera_persona   el agente hablando de sí como "el asistente"/"la IA"
	meta_narracion    "la conversación", "la sesión se…" (resumen de resumen)
	episodico         nota titulada "Joan me pide/cuenta…" (escena, no hallazgo)
	ingles            nota en inglés (el archivo es en español)
	sin_notas         hay polaroids pero cero notas
	titulo_largo      título > 80 chars (contrato del prompt)
	cuerpo_corto      texto < 120 chars (polaroid/nota vacía)
	duplicado         dos notas con el mismo título normalizado
	ref_roto          `distill_ref` de una nota apunta a un fichero que no existe
	placeholder       el modelo copió un ejemplo del prompt (fuga de plantilla)

Uso:
	python scripts/memento_audit.py --out /tmp/memento_audit.json
	python scripts/memento_audit.py --min-score 3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

DEIXIS = re.compile(
	r"\b(el|ese|dicho|dicha|el citado|la citada|el mencionado|la mencionada) (archivo|documento|sesi[oó]n|fichero|cambio|commit|comando|path|ruta)\b"
	r"|\b(ese|esta|dicha) (archivo|ruta|comando|funci[oó]n)\b"
	r"|\bel (anterior|antes mencionado)\b",
	re.I,
)
TONO = re.compile(
	r"\b(con calma|con iron[ií]a|con cari[nñ]o|en voz baja|con esa complicidad|como si fuera|"
	r"el tono (es|fue|era)|emocionalmente|con humor|con paciencia|con orgullo)\b",
	re.I,
)
TERCERA = re.compile(r"\b(el asistente|la asistente|el agente|la IA|el bot)\b", re.I)
META = re.compile(r"\b(la conversaci[oó]n|la sesi[oó]n se|el di[aá]logo|la interacci[oó]n)\b", re.I)
EPISODICO = re.compile(r"^joan me (pide|pidi[oó]|cuenta|cont[oó]|dice|dijo|explica|explic[oó]|muestra|mostr[oó]|asigna)", re.I)
PLACEHOLDER = re.compile(r"<la pieza>|<algo>|Real action|REAL moment", re.I)
FM = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)

PESO = {
	"deixis": 3,
	"placeholder": 4,
	"tono_inventado": 2,
	"episodico": 2,
	"tercera_persona": 2,
	"meta_narracion": 2,
	"sin_notas": 3,
	"ref_roto": 3,
	"duplicado": 1,
	"ingles": 1,
	"cuerpo_corto": 1,
	"titulo_largo": 1,
}


def _frontmatter(text: str) -> Tuple[Dict[str, str], str]:
	m = FM.match(text)
	if not m:
		return {}, text
	cab = {}
	for line in m.group(1).splitlines():
		if ":" in line:
			k, _, v = line.partition(":")
			cab[k.strip()] = v.strip()
	return cab, m.group(2).strip()


def _ingles(texto: str) -> bool:
	en = len(re.findall(r"\b(the|and|with|from|this|that|which|was|were)\b", texto, re.I))
	es = len(re.findall(r"\b(el|la|los|las|que|con|para|del|una|por)\b", texto, re.I))
	return en >= 5 and en > es


def _alrededor(txt: str, m: re.Match) -> str:
	return "…" + txt[max(0, m.start() - 35) : m.end() + 35].replace("\n", " ").strip() + "…"


def auditar_sesion(ses_dir: Path, root: Path) -> Dict[str, Any]:
	flags: Dict[str, List[str]] = defaultdict(list)
	distill = sorted((ses_dir / "distill").glob("*.md")) if (ses_dir / "distill").is_dir() else []
	notas = sorted((ses_dir / "annotate").glob("*.md")) if (ses_dir / "annotate").is_dir() else []

	engine = None
	for f in distill:
		cab, cuerpo = _frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
		engine = engine or cab.get("engine")
		for nombre, pat in (
			("deixis", DEIXIS),
			("tono_inventado", TONO),
			("tercera_persona", TERCERA),
			("meta_narracion", META),
			("placeholder", PLACEHOLDER),
		):
			m = pat.search(cuerpo)
			if m:
				flags[nombre].append(f"distill/{f.name}: {_alrededor(cuerpo, m)}")
		if len(cuerpo) < 120:
			flags["cuerpo_corto"].append(f"distill/{f.name} ({len(cuerpo)} chars)")
		if _ingles(cuerpo):
			flags["ingles"].append(f"distill/{f.name}")

	vistos = set()
	for f in notas:
		cab, cuerpo = _frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
		titulo = cab.get("title", "")
		if len(titulo) > 80:
			flags["titulo_largo"].append(f"annotate/{f.name} ({len(titulo)} chars)")
		if EPISODICO.match(titulo):
			flags["episodico"].append(f"annotate/{f.name}: {titulo[:70]}")
		for nombre, pat in (("deixis", DEIXIS), ("tono_inventado", TONO), ("tercera_persona", TERCERA), ("meta_narracion", META)):
			m = pat.search(cuerpo)
			if m:
				flags[nombre].append(f"annotate/{f.name}: {_alrededor(cuerpo, m)}")
		if len(cuerpo) < 120:
			flags["cuerpo_corto"].append(f"annotate/{f.name} ({len(cuerpo)} chars)")
		if _ingles(cuerpo):
			flags["ingles"].append(f"annotate/{f.name}")
		norm = re.sub(r"\W+", " ", titulo.lower()).strip()
		if norm in vistos:
			flags["duplicado"].append(f"annotate/{f.name}: {titulo[:60]}")
		vistos.add(norm)
		ref = cab.get("distill_ref", "")
		if ref and not (root / ref).exists():
			flags["ref_roto"].append(f"annotate/{f.name} → {ref}")

	if distill and not notas:
		flags["sin_notas"].append(f"{len(distill)} polaroids, 0 notas")

	score = sum(PESO.get(k, 1) * min(len(v), 5) for k, v in flags.items())
	return {
		"session": f"{ses_dir.parent.name}/{ses_dir.name}",
		"dir": str(ses_dir.relative_to(root)),
		"engine": engine,
		"polaroids": len(distill),
		"notas": len(notas),
		"score": score,
		"flags": {k: {"n": len(v), "ejemplos": v[:3]} for k, v in sorted(flags.items())},
	}


def main() -> None:
	ap = argparse.ArgumentParser(description="Auditoría read-only del árbol Memento")
	ap.add_argument("--root", default=None, help="raíz memento (default: la del config)")
	ap.add_argument("--out", default="/tmp/memento_audit.json", help="JSONL de salida")
	ap.add_argument("--min-score", type=int, default=0, help="sólo sesiones con score >= N (en el JSONL)")
	ap.add_argument("--limit", type=int, default=0, help="máximo de sesiones (0 = todas)")
	args = ap.parse_args()

	if args.root:
		root = Path(args.root)
	else:
		from red_pill.memento import get_memento_root

		root = get_memento_root()

	sesiones = sorted(d for d in root.glob("*/*/*") if d.is_dir() and ((d / "distill").is_dir() or (d / "annotate").is_dir()))
	if args.limit:
		sesiones = sesiones[: args.limit]

	filas = []
	for d in sesiones:
		try:
			filas.append(auditar_sesion(d, root))
		except Exception as e:  # una sesión ilegible no debe tumbar la auditoría
			print(f"[audit] {d}: {e}", file=sys.stderr)

	filas.sort(key=lambda r: -r["score"])
	out = Path(args.out)
	with out.open("w", encoding="utf-8") as fh:
		for r in filas:
			if r["score"] >= args.min_score:
				fh.write(json.dumps(r, ensure_ascii=False) + "\n")

	casos: Counter = Counter()
	for r in filas:
		for k, v in r["flags"].items():
			casos[k] += v["n"]

	print(f"sesiones auditadas: {len(filas)} · con algún hallazgo: {sum(1 for r in filas if r['score'])}")
	print(f"{'patrón':18s} {'casos':>7s} {'sesiones':>9s}")
	for k, n in casos.most_common():
		nses = sum(1 for r in filas if k in r["flags"])
		print(f"{k:18s} {n:7d} {nses:9d}")
	print(f"\nlistado: {out}")
	for r in filas[:10]:
		if not r["score"]:
			break
		pat = ", ".join(f"{k}×{v['n']}" for k, v in r["flags"].items())
		print(f"  {r['score']:3d}  {r['dir'][-46:]:48s} {pat}")


if __name__ == "__main__":
	main()
