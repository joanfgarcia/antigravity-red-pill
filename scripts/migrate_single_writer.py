#!/usr/bin/env python3
"""migrate_single_writer.py — migración de una instalación legacy al single-writer.

Para instalaciones que se ACTUALIZAN desde una versión previa al single-writer:
la vía legacy (`staging/` → consolidación) desaparece y work/social pasa a
alimentarse solo de Memento. Este migrador asegura que nada se pierde y deja la
instalación en el estado nuevo.

Pasos (dry-run por defecto):
1. COBERTURA: cada sesión del registry debe tener `raw/` o render en Memento; si
   falta alguna → ABORTA (no migrar con memoria sin archivar).
2. STAGING: lo que quede en `staging/` se archiva en `staging/_migrated_<ts>/`
   (no se borra).
3. BUFFER: `interaction_memories` más viejo que `INTERACTION_MAX_AGE_DAYS` se
   trima (el buffer es ventana corta; el archivo es Memento).
4. MARCA: escribe `state/single_writer_migrated.json` (idempotencia).

	uv run python scripts/migrate_single_writer.py            # dry-run
	uv run python scripts/migrate_single_writer.py --apply    # ejecuta
	uv run python scripts/migrate_single_writer.py --apply --force  # re-ejecutar

Instalaciones NUEVAS no lo necesitan (nacen sin legacy). El código legacy se
elimina en la demolición; este script es la red para quien ya tenía datos.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

# Permitir `python scripts/migrate_single_writer.py` (sys.path[0]=scripts/):
# el repo root entra en path para importar el helper de cobertura del purgador.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memento_purge_archive import _classify_session  # noqa: E402


def _marker_path() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir() / "single_writer_migrated.json"


def _staging_files() -> list[Path]:
	from red_pill.core.paths import get_staging_dir

	d = get_staging_dir()
	if not d.is_dir():
		return []
	return [p for p in d.iterdir() if p.is_file()]


def _coverage_missing() -> list[str]:
	"""Sesiones del registry sin raw/ ni render (no archivadas)."""
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry

	root = get_memento_root()
	reg = MementoRegistry()
	missing = []
	for source, sessions in reg.state.get("registry", {}).items():
		if not isinstance(sessions, dict):
			continue
		for sid, entry in sessions.items():
			dir_rel = (entry or {}).get("dir")
			if not dir_rel:
				continue
			if _classify_session(root, dir_rel) is None:
				missing.append(f"{source}|{sid}")
	return missing


def _trim_buffer(apply: bool) -> dict:
	"""Cuenta (y con --apply borra) turnos del buffer más viejos que el tope de edad."""
	from qdrant_client.http import models as qm

	import red_pill.config as cfg
	from red_pill.memory import MemoryManager

	mm = MemoryManager()
	if not mm.client.collection_exists("interaction_memories"):
		return {"total": 0, "trimmed": 0}
	max_age = int(getattr(cfg, "INTERACTION_MAX_AGE_DAYS", 30))
	cutoff = time.time() - max_age * 86400
	flt = qm.Filter(
		should=[
			qm.FieldCondition(key="timestamp", range=qm.Range(lt=cutoff)),
			qm.FieldCondition(key="created_at", range=qm.Range(lt=cutoff)),
		]
	)
	total = mm.client.count("interaction_memories", count_filter=flt, exact=True).count
	if apply and total:
		mm.client.delete("interaction_memories", points_selector=qm.FilterSelector(filter=flt), wait=True)
	return {"total": total, "trimmed": total if apply else 0, "max_age_days": max_age}


def main() -> int:
	ap = argparse.ArgumentParser(description="Migración al single-writer (dry-run por defecto).")
	ap.add_argument("--apply", action="store_true", help="Ejecuta (por defecto: dry-run)")
	ap.add_argument("--force", action="store_true", help="Re-ejecutar aunque ya esté migrado")
	args = ap.parse_args()

	marker = _marker_path()
	if marker.exists() and not args.force:
		print(f"[MIGRATE] ya migrado ({marker}) — nada que hacer (usa --force para re-ejecutar).")
		return 0

	print("[MIGRATE] 1) cobertura de Memento...")
	missing = _coverage_missing()
	if missing:
		print(f"[MIGRATE] ABORT: {len(missing)} sesión(es) sin raw/ ni render — no migrar con memoria sin archivar.")
		for m in missing[:10]:
			print(f"  - {m}")
		return 1
	print("[MIGRATE]    cobertura OK")

	staging = _staging_files()
	print(f"[MIGRATE] 2) staging: {len(staging)} fichero(s) pendiente(s) de la vía legacy")

	buf = _trim_buffer(apply=args.apply)
	print(f"[MIGRATE] 3) buffer: {buf['total']} turno(s) > {buf['max_age_days']}d ({'borrados' if args.apply else 'a borrar'})")

	if not args.apply:
		print("[MIGRATE] DRY-RUN — usa --apply para ejecutar (archivar staging + trim buffer + marca).")
		return 0

	if staging:
		from red_pill.core.paths import get_staging_dir

		dest = get_staging_dir() / f"_migrated_{int(time.time())}"
		dest.mkdir(parents=True, exist_ok=True)
		for p in staging:
			try:
				shutil.move(str(p), str(dest / p.name))
			except Exception as e:
				print(f"[MIGRATE] WARN no se pudo archivar {p.name}: {e}")
		print(f"[MIGRATE]    staging archivado en {dest}")

	marker.parent.mkdir(parents=True, exist_ok=True)
	marker.write_text(
		json.dumps({"migrated_at": time.time(), "staging_archived": len(staging), "buffer_trimmed": buf["trimmed"]}, indent=2),
		encoding="utf-8",
	)
	print(f"[MIGRATE] completado — marca en {marker}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
