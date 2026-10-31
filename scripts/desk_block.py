#!/usr/bin/env python3
"""Bloque gestionado del seed dentro de un documento del desk.

PROBLEMA QUE RESUELVE
---------------------
Hay ficheros del desk que son **de los dos**: el seed aporta una convención que
debe poder actualizarse, y el desk aporta identidad, familias y excepciones que
no pueden perderse. Tratarlos como germen entero revierte trabajo local;
tratarlos como puesto deja al desk con una copia vieja y nadie se entera.

La solución es la misma que ya usa `scripts/inject_anchor.py` para `CLAUDE.md`:
red-pill es **invitado, no dueño**. El seed mantiene sólo su región, delimitada:

<!-- REDPILL:BEGIN desk v=1 -->
…lo que mantiene el seed…
<!-- REDPILL:END desk -->

- **Frontmatter**: fuera del bloque, siempre del desk (title, author, related…).
- **Dentro del bloque**: la región del seed.
- **Después del bloque**: lo que el desk añada por su cuenta. Nunca se toca.

DECISIÓN, CON TRES TEXTOS
-------------------------
Igual que `scaffold_desk.sh` con los hashes, pero con el TEXTO en vez del hash,
porque aquí hay que fusionar, no sólo decidir. La base (`--baseline`, último
cuerpo sembrado) se guarda en el desk (`.germ.baseline/`).

base = cur   nadie tocó el bloque        → se pone el nuevo            updated
base = new   el seed no cambió           → se deja el del desk         local
base ≠ cur ≠ new                         → merge de 3 vías             merged
merge con conflicto                      → NO se escribe; el del seed queda al
lado como `*.seed-new`                     conflict

Un conflicto no es un fallo: o el desk sabe algo que al seed le falta (se
promociona al seed) o necesita una excepción (va FUERA del bloque).

USO
---
desk_block.py splice --seed S --desk D --baseline B
desk_block.py init   --seed S --desk D --baseline B   # envuelve el cuerpo actual
desk_block.py remove --desk D                         # disable / uninstall

Salida: una línea `RESULT: <palabra>` por stdout (la consume `scaffold_desk.sh`);
el detalle legible va por stderr.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ANCHOR = "desk"
BLOCK_VERSION = 1
SEED_NEW_SUFFIX = ".seed-new"
FRONTMATTER_RE = re.compile(r"\A(---\n.*?\n---\n)", re.DOTALL)
BLOCK_RE = re.compile(
	r"<!-- REDPILL:BEGIN %s(?: v=\d+)? -->\n(.*?)\n<!-- REDPILL:END %s -->" % (ANCHOR, ANCHOR),
	re.DOTALL,
)


def say(msg: str) -> None:
	print(f"[desk_block] {msg}", file=sys.stderr)


def split_frontmatter(text: str) -> tuple[str, str]:
	"""Devuelve (frontmatter, resto). El frontmatter es SIEMPRE del desk."""
	m = FRONTMATTER_RE.match(text)
	if not m:
		return "", text
	return m.group(1), text[m.end() :]


def build_block(body: str) -> str:
	begin = f"<!-- REDPILL:BEGIN {ANCHOR} v={BLOCK_VERSION} -->"
	end = f"<!-- REDPILL:END {ANCHOR} -->"
	return f"{begin}\n{body.strip()}\n{end}"


def extract(body: str) -> tuple[str, str, str] | None:
	"""(antes, cuerpo_del_bloque, después) o None si el fichero no tiene bloque."""
	m = BLOCK_RE.search(body)
	if not m:
		return None
	return body[: m.start()], m.group(1).strip(), body[m.end() :]


def body_of(text: str) -> str:
	"""Cuerpo del seed: si ya trae marcas, lo de dentro; si no, el cuerpo entero."""
	_body = split_frontmatter(text)[1]
	parts = extract(_body)
	return (parts[1] if parts else _body).strip()


def _from_seed(seed_text: str) -> str:
	"""Documento nuevo del desk a partir del seed: frontmatter + bloque con MARCAS.

	No se copia el seed tal cual a propósito: si al seed se le olvidan las marcas,
	copiarlo dejaría un fichero sin región gestionada y la siguiente pasada añadiría
	el bloque entero al final (duplicando el contenido).
	"""
	fm, _body = split_frontmatter(seed_text)
	return fm + "\n" + build_block(body_of(seed_text)) + "\n"


def _merge3(ours: str, base: str, theirs: str) -> tuple[bool, str]:
	"""Merge de 3 vías con `git merge-file` (sin repo, sin índice)."""
	git = shutil.which("git")
	if not git:
		return False, ""
	with tempfile.TemporaryDirectory(prefix="desk_block_") as tmp:
		paths = {}
		for name, content in (("ours", ours), ("base", base), ("theirs", theirs)):
			p = Path(tmp) / name
			p.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
			paths[name] = str(p)
		proc = subprocess.run(
			[git, "merge-file", "-p",
				"-L", "desk", "-L", "base", "-L", "seed",
				paths["ours"], paths["base"], paths["theirs"]],
			capture_output=True,
			text=True,
		)
		# 0 = limpio; 1..127 = número de conflictos; <0 = error.
		return proc.returncode == 0, proc.stdout


def _write_atomic(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(path.name + ".tmp")
	tmp.write_text(text, encoding="utf-8")
	tmp.replace(path)


def _read(path: Path) -> str:
	return path.read_text(encoding="utf-8") if path.exists() else ""


def cmd_init(seed: Path, desk: Path, baseline: Path) -> str:
	"""Envuelve el cuerpo ACTUAL del desk en marcas y anota el cuerpo del seed como base.

	La base es el cuerpo del seed, no el del desk: lo que el desk tenga de más
	queda como "modificación local" y el merge lo respetará mientras no choque.
	Este comando no cambia una sola línea del contenido del desk.
	"""
	seed_text = _read(seed)
	desk_text = _read(desk)
	if not desk_text:
		_write_atomic(desk, _from_seed(seed_text))
		_write_atomic(baseline, body_of(seed_text))
		return "created"

	fm, body = split_frontmatter(desk_text)
	if extract(body) is not None:
		_write_atomic(baseline, body_of(seed_text))
		return "unchanged"

	_write_atomic(desk, fm + "\n" + build_block(body) + "\n")
	_write_atomic(baseline, body_of(seed_text))
	return "wrapped"


def cmd_splice(seed: Path, desk: Path, baseline: Path) -> str:
	seed_text = _read(seed)
	new_body = body_of(seed_text)
	if not _read(desk):
		_write_atomic(desk, _from_seed(seed_text))
		_write_atomic(baseline, new_body)
		return "created"

	desk_text = _read(desk)
	fm, body = split_frontmatter(desk_text)
	parts = extract(body)
	if parts is None:
		# Fichero antiguo sin bloque: se añade al final, sin tocar lo que ya hay.
		_write_atomic(desk, fm + "\n" + body.rstrip() + "\n\n" + build_block(new_body) + "\n")
		_write_atomic(baseline, new_body)
		say(f"{desk.name}: no tenía bloque; se añade al final sin tocar el resto.")
		return "appended"

	before, cur, after = parts
	base = _read(baseline).strip()

	if cur == new_body:
		_write_atomic(baseline, new_body)
		return "unchanged"
	if not base:
		# Sin base no hay merge posible: manda el desk y se adopta el seed como referencia.
		_write_atomic(baseline, new_body)
		say(f"{desk.name}: sin base guardada; se conserva el bloque del desk y se adopta el del seed como referencia.")
		return "local"
	if base == cur:
		_write_atomic(desk, fm + "\n" + before + build_block(new_body) + after)
		_write_atomic(baseline, new_body)
		return "updated"
	if base == new_body:
		return "local"

	clean, merged = _merge3(cur, base, new_body)
	if clean and merged.strip():
		_write_atomic(desk, fm + "\n" + before + build_block(merged) + after)
		_write_atomic(baseline, new_body)
		return "merged"

	# Conflicto: NO se toca el desk. La versión nueva queda al lado, entera.
	_write_atomic(Path(str(desk) + SEED_NEW_SUFFIX), build_block(new_body) + "\n")
	say(
		f"{desk.name}: el desk y el seed han cambiado el bloque. No se ha tocado nada; "
		f"la versión del seed está en {desk.name}{SEED_NEW_SUFFIX}. Resuelve a mano, "
		f"promociona al seed lo que sea general o mueve tu excepción FUERA del bloque."
	)
	return "conflict"


def cmd_remove(desk: Path) -> str:
	desk_text = _read(desk)
	if not desk_text:
		return "absent"
	fm, body = split_frontmatter(desk_text)
	parts = extract(body)
	if parts is None:
		return "unchanged"
	before, _cur, after = parts
	_write_atomic(desk, fm + "\n" + (before + after).strip() + "\n")
	return "removed"


def main() -> int:
	ap = argparse.ArgumentParser(
		description="Bloque gestionado del seed dentro de un documento del desk (red-pill es invitado).",
		epilog=(
			"El frontmatter y lo que quede FUERA de las marcas pertenece siempre al desk.\n"
			"Dentro de las marcas manda el seed; si ambos cambian, merge de 3 vías y, si\n"
			"hay conflicto, no se escribe nada y la versión nueva queda al lado.\n"
		),
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	sub = ap.add_subparsers(dest="cmd", required=True)
	for name, helptext in (
		("splice", "Funde el bloque del seed en el documento del desk."),
		("init", "Envuelve el cuerpo actual del desk en marcas (migración)."),
		("remove", "Quita el bloque (el resto del documento se queda)."),
	):
		s = sub.add_parser(name, help=helptext)
		s.add_argument("--desk", type=Path, required=True)
		if name != "remove":
			s.add_argument("--seed", type=Path, required=True)
			s.add_argument("--baseline", type=Path, required=True)
	args = ap.parse_args()

	if args.cmd == "remove":
		result = cmd_remove(args.desk)
	elif args.cmd == "init":
		result = cmd_init(args.seed, args.desk, args.baseline)
	else:
		result = cmd_splice(args.seed, args.desk, args.baseline)

	print(f"RESULT: {result}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
