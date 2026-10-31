#!/usr/bin/env python3
"""Índice de familias de `planner/design/` — estado de todo el árbol de un vistazo.

QUÉ RESUELVE
------------
`planner/design/` tiene una veintena de familias y no hay forma de saber en qué
está cada una sin abrirlas una a una. Las bandejas dicen **dónde vive** un
documento; el `status` dice **en qué está** (ver `planner/README.md` §Modelo).
Este índice cruza las dos cosas por familia.

GENERADO, NO ESCRITO A MANO
---------------------------
Un recuento copiado en un README se queda viejo el día siguiente y nadie lo nota.
Este fichero se regenera tras mover, añadir o cerrar documentos:

    python3 planner/tools/families.py                          # imprimir
    python3 planner/tools/families.py -o planner/design/INDEX.md

La columna "Estados" es un recuento literal del frontmatter, no un juicio: si una
familia mezcla `implemented` e `in-progress`, se ven los dos. La columna "Puerta"
señala si la familia tiene `INDEX.md` o `README.md` como entrada; un `—` ahí es
una familia a la que le falta puerta.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "planner" / "design"

# Orden de presentación de los estados dentro de una familia: primero lo que está
# vivo, al final lo cerrado. Sólo afecta a cómo se lee la fila, no a qué se cuenta.
STATUS_ORDER = (
	"in-progress",
	"implemented",
	"ratified",
	"in-design",
	"draft",
	"active",
	"blocked",
	"paused",
	"pending",
	"maturing",
	"parked",
	"closed",
	"archived",
	"superseded",
	"unknown",
)

DOOR_NAMES = ("INDEX.md", "README.md")


def _family_docs(fam: Path) -> list[tuple[str, str, str]]:
	"""[(nombre, status, updated)] de los .md de la familia, incluidos los anidados."""
	out = []
	for p in sorted(fam.rglob("*.md")):
		fm = panel.parse_frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
		out.append((p.name, str(fm.get("status") or "unknown"), str(fm.get("updated") or "")))
	return out


def _door(fam: Path) -> str:
	for name in DOOR_NAMES:
		if (fam / name).exists():
			return name
	return "—"


def _status_cell(statuses: Counter) -> str:
	parts = []
	for st in STATUS_ORDER:
		if statuses.get(st):
			parts.append(f"`{st}` ×{statuses[st]}" if statuses[st] > 1 else f"`{st}`")
	for st, n in sorted(statuses.items()):
		if st not in STATUS_ORDER:
			parts.append(f"`{st}` ×{n}" if n > 1 else f"`{st}`")
	return " · ".join(parts) or "—"


def build(root: Path = DESIGN) -> str:
	fams = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))
	rows = []
	total_status: Counter = Counter()
	sin_puerta = []
	for fam in fams:
		docs = _family_docs(fam)
		statuses = Counter(st for _n, st, _u in docs)
		total_status.update(statuses)
		door = _door(fam)
		if door == "—":
			sin_puerta.append(fam.name)
		last = max((u for _n, _s, u in docs if u), default="")
		rows.append((fam, docs, statuses, door, last))

	lines = [
		"---",
		'type: index',
		'title: "Diseño — las familias y su estado (generado)"',
		"status: active",
		f"created: {date.today().isoformat()}",
		'author: "planner/tools/families.py (generado)"',
		"project: aleth-core",
		"tags: [index, generado, familias, design, estado]",
		"---",
		"",
		"> **Generado por `planner/tools/families.py`** — NO editar a mano; regenéralo.",
		"> Las bandejas dicen dónde vive un documento; el `status` dice en qué está.",
		"> Esta tabla cruza las dos cosas por familia.",
		"",
		f"**{len(fams)} familias · {sum(len(d) for _f, d, _s, _p, _u in rows)} documentos**"
		+ (f" · **{len(sin_puerta)} sin puerta**" if sin_puerta else ""),
		"",
		"| Familia | Docs | Estados | Último cambio | Puerta |",
		"|---|---|---|---|---|",
	]
	for fam, docs, statuses, door, last in rows:
		link = f"[`{fam.name}/`]({fam.name}/)" + (f" → `{door}`" if door != "—" else "")
		lines.append(
			f"| {link} | {len(docs)} | {_status_cell(statuses)} | {last or '—'} | {door if door != '—' else '**falta**'} |"
		)

	lines += ["", "**Estados en todo diseño:** " + _status_cell(total_status), ""]
	if sin_puerta:
		lines.append("Familias sin puerta (les falta `INDEX.md` o `README.md`):")
		lines.append("")
		for name in sin_puerta:
			lines.append(f"- `{name}/`")
		lines.append("")
	return "\n".join(lines)


def main() -> int:
	ap = argparse.ArgumentParser(
		description="Índice de familias de planner/design (generado, no escrito a mano).",
		epilog=(
			"Sin argumentos imprime por stdout; con -o escribe el fichero.\n"
			"Cada fila: familia, nº de documentos, recuento de estados, último cambio y puerta.\n"
		),
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	ap.add_argument("-o", "--output", metavar="FICHERO", help="Fichero destino; '-' = stdout.")
	ap.add_argument("--root", type=Path, default=DESIGN, help="Raíz de familias (default: planner/design).")
	args = ap.parse_args()

	if not args.root.is_dir():
		print(f"[families] no existe {args.root}", file=sys.stderr)
		return 2

	text = build(args.root)
	if args.output and args.output != "-":
		Path(args.output).write_text(text, encoding="utf-8")
		print(f"índice escrito en {args.output}")
	else:
		print(text)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
