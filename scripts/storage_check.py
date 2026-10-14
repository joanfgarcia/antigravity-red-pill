#!/usr/bin/env python3
"""storage_check.py — detecta DUPLICADOS REALES de modelos en el disco.

Regla del proyecto: *un componente, un fichero* (docs/CORE/MODEL_STORAGE.md).
Esta herramienta lo verifica agrupando por tamaño, confirmando por hash (sha256)
e **ignorando hardlinks** (mismo inodo = un solo dato en disco, no es duplicado).

Reporta:
  - **duplicados reales** (mismo contenido, inodos distintos) + bytes recuperables;
  - **hardlinks** (mismo inodo) → informativo (no ocupan de más);
  - restos **`.incomplete`** (descargas abortadas de HF) → basura;
  - **modelos en >1 caché HF** (mismo repo en sitios distintos) → doble copia.

Uso:
  storage_check.py [--roots R [R ...]] [--min-size MB] [--json]
Defaults de roots: ~/.local/share/red-pill/models, ~/opt/*-forge, ~/.cache/huggingface
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

MB = 1024 * 1024


def _default_roots() -> list:
	roots = [Path.home() / ".local" / "share" / "red-pill" / "models"]
	opt = Path.home() / "opt"
	if opt.is_dir():
		roots += [d for d in opt.glob("*-forge") if d.is_dir()]
	# modelos custom (no-HF / composiciones multi-repo)
	roots.append(opt / "red-pill-custom-image-models")
	roots.append(Path.home() / ".cache" / "huggingface")
	return [r for r in roots if r.exists()]


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for block in iter(lambda: f.read(chunk), b""):
			h.update(block)
	return h.hexdigest()


def _scan(roots: list, min_size: int):
	"""Devuelve (por_tamano {size: [(path, inode)]}, incompletes []).

	Ignora symlinks (en HF los snapshots son punteros; el dato real es el blob).
	"""
	by_size: dict = defaultdict(list)
	incompletes: list = []
	for root in roots:
		for p in Path(root).rglob("*"):
			try:
				if p.is_symlink() or not p.is_file():
					continue
				name = p.name
				if name.endswith(".incomplete"):
					incompletes.append(p)
					continue
				st = p.stat()
				if st.st_size < min_size:
					continue
				by_size[st.st_size].append((p, st.st_ino))
			except OSError:
				continue
	return by_size, incompletes


def _duplicates(by_size: dict):
	"""Duplicados reales (mismo hash, INODOS distintos) + grupos hardlink.

	Dentro de un grupo de contenido, las rutas que comparten inodo son hardlinks
	(un solo dato) → se colapsan a una; solo cuenta como duplicado real si hay
	**más de un inodo**.
	"""
	real, hardlinks = [], []
	for size, entries in by_size.items():
		if len(entries) < 2:
			continue
		by_hash: dict = defaultdict(list)
		for p, ino in entries:
			try:
				by_hash[_sha256(p)].append((p, ino))
			except OSError:
				continue
		for digest, group in by_hash.items():
			if len(group) < 2:
				continue
			inode_paths: dict = defaultdict(list)
			for p, ino in group:
				inode_paths[ino].append(str(p))
			if len(inode_paths) > 1:
				# un representante DETERMINISTA por inodo (ordenado)
				real.append({"size": size, "sha256": digest, "paths": sorted(sorted(v)[0] for v in inode_paths.values())})
			else:
				# todas las rutas comparten inodo → hardlink (no ocupan de más)
				hardlinks.append({"size": size, "paths": sorted(p for p, _ in group)})
	return real, hardlinks


def _hf_models_in_multiple_caches(roots: list) -> dict:
	"""Repos HF (models--org--name) presentes en más de un root."""
	where: dict = defaultdict(set)
	for root in roots:
		for m in Path(root).rglob("models--*"):
			if m.is_dir() and m.parent.name == "hub":
				where[m.name].add(str(m.parent.parent))
	return {k: sorted(v) for k, v in where.items() if len(v) > 1}


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--roots", nargs="+", help="directorios a escanear (def: LLM + forges + ~/.cache)")
	ap.add_argument("--min-size", type=int, default=50, help="tamaño mínimo en MB (def 50)")
	ap.add_argument("--json", action="store_true", help="salida JSON")
	args = ap.parse_args()

	roots = [Path(r).expanduser() for r in args.roots] if args.roots else _default_roots()
	by_size, incompletes = _scan(roots, args.min_size * MB)
	real, hardlinks = _duplicates(by_size)
	multi_cache = _hf_models_in_multiple_caches([r for r in roots if r.exists()])

	reclaim = sum(d["size"] * (len(d["paths"]) - 1) for d in real)
	report = {
		"roots": [str(r) for r in roots],
		"min_size_mb": args.min_size,
		"real_duplicates": real,
		"reclaimable_mb": round(reclaim / MB, 1),
		"hardlink_groups": len(hardlinks),
		"incomplete_files": [str(p) for p in incompletes],
		"incomplete_mb": round(sum(p.stat().st_size for p in incompletes if p.exists()) / MB, 1),
		"hf_models_in_multiple_caches": multi_cache,
	}

	if args.json:
		print(json.dumps(report, ensure_ascii=False, indent=2))
		return 0

	print(f"[storage] raíces: {', '.join(report['roots'])}  (min {args.min_size} MB)")
	if real:
		print(f"\n❌ DUPLICADOS REALES ({len(real)} grupos, ~{report['reclaimable_mb']} MB recuperables):")
		for d in real:
			print(f"  {d['size'] / MB:.1f} MB  sha256={d['sha256'][:12]}…")
			for p in d["paths"]:
				print(f"     {p}")
	else:
		print("\n✅ Sin duplicados reales.")
	print(f"\n🔗 Grupos hardlink (mismo inodo, NO ocupan de más): {report['hardlink_groups']}")
	if incompletes:
		print(f"\n🗑️  Ficheros .incomplete ({report['incomplete_mb']} MB) — borrar: find <cache> -name '*.incomplete' -delete")
		for p in report["incomplete_files"]:
			print(f"     {p}")
	if multi_cache:
		print("\n📦 Modelos HF en >1 caché (doble copia):")
		for name, locs in multi_cache.items():
			print(f"  {name.replace('models--', '')}: {', '.join(locs)}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
