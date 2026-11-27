#!/usr/bin/env python3
"""Repara notas con DOBLE frontmatter (AD-151, MEM-009 P0).

Causa: `_frontmatter_block` escribía escalares crudos y un título que empieza
por backtick (o por comilla, `#`, `- `, `: `) rompía el YAML. `titles._split_
frontmatter` se tragaba la excepción y `_write_note` envolvía el fichero entero
en una cabecera nueva con solo `title/title_version/title_engine`: el bloque
original quedaba dentro del cuerpo y `session_id`, `scope`, `work_score` y
`ascended` desaparecían del header. Medido el 2026-11-28 en la sesión
`opencode-ses_f839399b…`: 34 de 983 notas.

Qué hace (una pasada, idempotente):
- Detecta `cuerpo.lstrip().startswith("---")` tras el primer bloque.
- Parsea el bloque interior con `titles._split_frontmatter` (fallback incluido:
  título crudo a mano + parseo del resto).
- Fusiona: interior + `title`/`title_version`/`title_engine` del exterior (el
  título SELLADO manda; el interior es el provisional, ya inválido).
- Reescribe con `yaml.safe_dump`, MISMO nombre de fichero y MISMO cuerpo.
- No toca ninguna otra nota. Segunda pasada: 0 reescritas.

Uso:
	scripts/memento_repair_double_frontmatter.py --annotate-dir <ruta> --dry-run
	scripts/memento_repair_double_frontmatter.py --annotate-dir <ruta>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_BACKUP = Path("/tmp/opencode/mem009-backup")
_SEALED = ("title", "title_version", "title_engine")


def split_first_block(text: str) -> Tuple[Dict[str, Any], str]:
	"""Primer bloque → (dict o {} si no parsea, resto tal cual)."""
	if not text.startswith("---"):
		return {}, text
	end = text.find("\n---", 3)
	if end < 0:
		return {}, text
	try:
		fm = yaml.safe_load(text[3:end])
	except yaml.YAMLError:
		fm = None
	return (fm if isinstance(fm, dict) else {}), text[end + 4 :]


def is_double(text: str) -> bool:
	"""¿El cuerpo tras el primer bloque empieza por otro bloque YAML?"""
	_raw, body = split_first_block(text)
	return body.lstrip().startswith("---")


def find_doubles(annotate_dir: Path) -> List[Path]:
	return [p for p in sorted(annotate_dir.glob("[0-9][0-9][0-9]-*.md")) if is_double(p.read_text(encoding="utf-8"))]


def dump_frontmatter(fm: Dict[str, Any]) -> str:
	"""Bloque YAML con una clave por línea, contenedores en flow (estilo del corpus).

	Se serializa campo a campo —no el dict entero— para conservar el aspecto de
	las 949 notas limpias (`texture: {...}`, `quality_flags: []`) y que el diff de
	las 34 reparadas sea el mínimo: solo la línea `title:` cambia de verdad.
	`yaml.safe_dump` decide las comillas (cita backticks, comillas, `#`, `: `).
	"""
	lines = ["---"]
	for key, value in fm.items():
		if isinstance(value, (dict, list)):
			lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
		else:
			lines.append(yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False, width=4096).rstrip())
	lines.append("---")
	block = "\n".join(lines)
	# Guarda: lo que se va a escribir DEBE parsear y valer lo mismo.
	if yaml.safe_load(block.split("\n", 1)[1].rsplit("\n---", 1)[0]) != fm:
		raise ValueError("la cabecera serializada no round-trip; no se escribe")
	return block


def plan(path: Path) -> Dict[str, Any]:
	"""Nota doble → fichero reparado (mismo nombre, mismo cuerpo) + diagnóstico."""
	from red_pill.memento.agentic.titles import _split_frontmatter

	raw = path.read_text(encoding="utf-8")
	outer, body = split_first_block(raw)
	if not body.lstrip().startswith("---"):
		raise ValueError(f"{path.name}: no tiene doble frontmatter")
	# El parser de producción, con su fallback: si esto falla, el script falla.
	inner_fm, inner_body = _split_frontmatter(body.lstrip("\n"), path)
	if not inner_fm:
		raise ValueError(f"{path.name}: el bloque interior está vacío")
	merged: Dict[str, Any] = dict(inner_fm)
	for key in _SEALED:
		if key in outer:
			merged[key] = outer[key]
	return {
		"path": path,
		"outer": outer,
		"inner": inner_fm,
		"merged": merged,
		"body": inner_body,
		"repaired": f"{dump_frontmatter(merged)}\n\n{inner_body}",
		"recovered": sorted(set(inner_fm) - set(outer)),
	}


def main(argv: List[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description="Repara notas con doble frontmatter (AD-151)")
	ap.add_argument("--annotate-dir", required=True, type=Path, help="directorio annotate/ de la sesión")
	ap.add_argument("--dry-run", action="store_true", help="solo informa; no escribe ni copia nada")
	ap.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP, help=f"backup de las notas tocadas (default {DEFAULT_BACKUP})")
	args = ap.parse_args(argv)

	annotate_dir: Path = args.annotate_dir.expanduser()
	if not annotate_dir.is_dir():
		print(f"ERROR: no existe {annotate_dir}", file=sys.stderr)
		return 2
	files = sorted(annotate_dir.glob("[0-9][0-9][0-9]-*.md"))
	doubles = find_doubles(annotate_dir)
	print(f"notas: {len(files)} | dobles: {len(doubles)} | modo: {'DRY-RUN' if args.dry_run else 'ESCRITURA'}")

	plans: List[Dict[str, Any]] = []
	for path in doubles:
		try:
			plans.append(plan(path))
		except Exception as exc:  # noqa: BLE001 — se reporta la nota y se sigue
			print(f"ERROR en {path.name}: {exc}", file=sys.stderr)
	if len(plans) != len(doubles):
		print(f"ERROR: {len(doubles) - len(plans)} nota(s) no se pueden reparar sin intervención", file=sys.stderr)

	if plans and not args.dry_run:
		args.backup_dir.mkdir(parents=True, exist_ok=True)
		for item in plans:
			target = args.backup_dir / item["path"].name
			if not target.exists():  # nunca pisar el backup original
				target.write_text(item["path"].read_text(encoding="utf-8"), encoding="utf-8")

	if args.dry_run:
		for item in plans:
			print(f"  [dry] {item['path'].name}: recuperaría {len(item['recovered'])} campo(s): {', '.join(item['recovered'][:8])}")
		print(f"backup destino (si se escribe): {args.backup_dir}")
		return 0

	rewritten = 0
	for item in plans:
		item["path"].write_text(item["repaired"], encoding="utf-8")
		rewritten += 1

	# Verificación en la misma pasada: 0 dobles y cuerpo idéntico al original.
	after = find_doubles(annotate_dir)
	mismatch = 0
	for item in plans:
		_raw, body = split_first_block(item["path"].read_text(encoding="utf-8"))
		if body.lstrip("\n") != item["body"]:
			mismatch += 1
			print(f"ERROR: cuerpo distinto en {item['path'].name}", file=sys.stderr)
	print(
		f"reescritas: {rewritten} | saltadas: {len(files) - len(doubles)} "
		f"| dobles restantes: {len(after)} | cuerpos distintos: {mismatch}"
	)
	return 0 if not after and not mismatch and len(plans) == len(doubles) else 1


if __name__ == "__main__":
	raise SystemExit(main())
