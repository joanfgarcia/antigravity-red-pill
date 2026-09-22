#!/usr/bin/env python3
"""Memento Lab — diagnostic workbench for the memory pipeline (raw → distill → annotate/refine → ascensión).

QUÉ ES
	Workbench (NO es un test de CI) para las sesiones recurrentes de calidad de
	memoria (MEM-006): mide el embudo de segmentación, audita la calidad de las
	notas y permite anotar UNA sesión en un árbol temporal sin tocar el real.

POR QUÉ / HISTORIA
	Nació el 2026-09-22, en la sesión de recalibración (MEM-006 + RFC-003). Sus
	piezas vivían en scripts efímeros de /tmp: el embudo de segmentación (9.424
	refines con solo 4.556 cuerpos únicos → la idea no se materializaba), los
	proxies de calidad de los pilotos de annotate (voz 1ª persona, near-dups,
	longitudes) y el banco de pruebas de una sesión. El arnés de estabilidad del
	scorer ya se consolidó en `scripts/memento_recalibrate.py` (`audit-stability`).

SUBCOMANDOS
	funnel [--root R] [--source SRC]
		Embudo: sesiones → splits → distills → annotate/refine → cuerpos únicos;
		grupos duplicados, ideas por source_lines, longitudes de distill/notas.

	quality [--root R] [--kind annotate|refine|all] [--session DIR]
		Calidad de las notas: n, únicas, near-dups (tokens >0.6), longitud
		p50/p90/max, % >600, % 1ª persona, flags (voice/gender/identity).

	annotate --session DIR [--root R] [--out /tmp/x] [--no-rewrite]
		Anota UNA sesión en un árbol temporal (banco de pruebas de prompts):
		copia su memento/, ejecuta la etapa real y reporta métricas + ejemplos.

Uso: uv run python tools/memento_lab.py <subcomando> [...]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
	sys.path.insert(0, str(REPO / "src"))


def _root(value: str | None) -> Path:
	from red_pill.memento import get_memento_root

	return Path(value) if value else Path(get_memento_root())


def _parse(txt: str):
	m = re.match(r"^---\n(.*?)\n---\n(.*)", txt, re.S)
	fm = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M)) if m else {}
	body = re.sub(r"\s+", " ", m.group(2)).strip() if m else txt
	return fm, body


def _tokens(text: str) -> set:
	return set(re.findall(r"[a-záéíóúüñ]{4,}", text.lower()))


def _sessions(root: Path) -> list:
	return sorted({str(p.parent.parent.relative_to(root)) for p in root.rglob("memento/index.md") if len(p.parent.parent.relative_to(root).parts) >= 3})


def cmd_funnel(args) -> None:
	root = _root(args.root)
	sessions = _sessions(root)
	if args.source:
		sessions = [s for s in sessions if f"/{args.source}/" in f"/{s}/"]
	splits = notes = 0
	dlens, nlens, bodies = [], [], []
	by_src = collections.Counter()
	for s in sessions:
		base = root / s
		splits += len(list((base / "memento").glob("[0-9][0-9][0-9]-*.md")))
		for d in (base / "distill").glob("*.md") if (base / "distill").is_dir() else []:
			_fm, body = _parse(d.read_text(encoding="utf-8", errors="replace"))
			dlens.append(len(body))
		for kind in ("annotate", "refine"):
			for f in (base / kind).glob("*.md") if (base / kind).is_dir() else []:
				fm, body = _parse(f.read_text(encoding="utf-8", errors="replace"))
				notes += 1
				nlens.append(len(body))
				bodies.append(hashlib.sha256(body.encode("utf-8")).hexdigest())
				by_src[str(fm.get("split_ref") or fm.get("source_lines") or "?")] += 1
	uniq = len(set(bodies))

	def q(values: list, p: float):
		return sorted(values)[int((len(values) - 1) * p)] if values else None

	print(
		json.dumps(
			{
				"sesiones": len(sessions),
				"splits": splits,
				"distills": len(dlens),
				"distill_len_p50_p90_max": (q(dlens, 0.5), q(dlens, 0.9), max(dlens) if dlens else None),
				"notas": notes,
				"cuerpos_unicos": uniq,
				"ratio_notas_por_cuerpo": round(notes / max(1, uniq), 2),
				"nota_len_p50_p90_max": (q(nlens, 0.5), q(nlens, 0.9), max(nlens) if nlens else None),
				"max_ideas_por_source": max(by_src.values(), default=0),
			},
			indent=2,
		)
	)


def cmd_quality(args) -> None:
	from red_pill.memento.agentic import is_first_person, quality_flags

	root = _root(args.root)
	sessions = [args.session] if args.session else _sessions(root)
	kinds = ("annotate", "refine") if args.kind == "all" else (args.kind,)
	texts, flags_count, sessions_hit = [], collections.Counter(), 0
	for s in sessions:
		hit = False
		for kind in kinds:
			for f in (root / s / kind).glob("*.md") if (root / s / kind).is_dir() else []:
				fm, body = _parse(f.read_text(encoding="utf-8", errors="replace"))
				texts.append(body)
				hit = True
				for fl in ("voice", "gender", "identity"):
					if fl in (fm.get("quality_flags") or ""):
						flags_count[fl] += 1
				if not fm.get("quality_flags"):
					for fl in quality_flags(body):
						flags_count[fl] += 1
		sessions_hit += int(hit)
	toks = [_tokens(t) for t in texts]
	near = sum(1 for i in range(len(toks)) for j in range(i + 1, len(toks)) if toks[i] and toks[j] and len(toks[i] & toks[j]) / min(len(toks[i]), len(toks[j])) > 0.6)
	lens = sorted(len(t) for t in texts)
	def q(p: float):
		return lens[int((len(lens) - 1) * p)] if lens else None
	print(
		json.dumps(
			{
				"kinds": kinds,
				"sesiones_con_notas": sessions_hit,
				"notas": len(texts),
				"unicas": len({t for t in texts}),
				"pares_near_dup": near,
				"len_p50_p90_max": (q(0.5), q(0.9), lens[-1] if lens else None),
				"pct_gt_600": round(100 * sum(1 for x in lens if x > 600) / max(1, len(lens)), 1),
				"pct_primera_persona": round(100 * sum(1 for t in texts if is_first_person(t)) / max(1, len(texts)), 1),
				"flags": dict(flags_count),
			},
			indent=2,
		)
	)


def cmd_annotate(args) -> None:
	from red_pill.memento.agentic import annotate_session, http_transport

	root = _root(args.root)
	out = Path(args.out) if args.out else Path("/tmp/memento_lab")
	dst = out / args.session
	if dst.exists():
		shutil.rmtree(dst)
	dst.mkdir(parents=True, exist_ok=True)
	shutil.copytree(root / args.session / "memento", dst / "memento", dirs_exist_ok=True)
	rewrite = not args.no_rewrite
	max_sig = annotate_session(out, args.session, "lab", "lab", http_transport, voice_rewrite=rewrite)
	files = sorted((dst / "annotate").glob("*.md"))
	print(json.dumps({"sesion": args.session, "voice_rewrite": rewrite, "notas": len(files), "max_significance": round(float(max_sig), 2), "salida": str(dst)}, indent=2))
	for f in files[:5]:
		_fm, body = _parse(f.read_text(encoding="utf-8", errors="replace"))
		print(f"  - {body[:160]}")


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	sub = parser.add_subparsers(dest="cmd", required=True)
	p = sub.add_parser("funnel", help="Embudo de segmentación del árbol.")
	p.add_argument("--root", default=None)
	p.add_argument("--source", default=None, help="Filtra por fuente (p.ej. antigravity).")
	p.set_defaults(func=cmd_funnel)
	p = sub.add_parser("quality", help="Proxies de calidad de las notas.")
	p.add_argument("--root", default=None)
	p.add_argument("--kind", choices=["annotate", "refine", "all"], default="all")
	p.add_argument("--session", default=None, help="Limita a una sesión (dir_rel).")
	p.set_defaults(func=cmd_quality)
	p = sub.add_parser("annotate", help="Anota una sesión en árbol temporal (banco de pruebas).")
	p.add_argument("--session", required=True, help="dir_rel de la sesión en el árbol real.")
	p.add_argument("--root", default=None)
	p.add_argument("--out", default=None, help="Árbol temporal de salida (default /tmp/memento_lab).")
	p.add_argument("--no-rewrite", action="store_true", help="Sin paso de rewrite de voz.")
	p.set_defaults(func=cmd_annotate)
	args = parser.parse_args()
	args.func(args)


if __name__ == "__main__":
	main()
