#!/usr/bin/env python3
"""Auditoría de pérdidas silenciosas en el árbol Memento (E-97e9d2).

Read-only: no escribe registry, ni índice, ni notas. Vigila la clase de fallo
que descubrió la hermana: una fase que se declara completa sin producir memoria.

Huellas:

	1. FAIL  agéntico **sellado** (hash del memento vigente, `annotate_pending`
		en False) y la sesión no tiene ni `annotate/` ni notas en `refine/`.
		Es la firma del pase que "procesó" sin escribir nada: la rama rota
		nunca llega a crear `annotate/`.
	2. FAIL  `memento/index.md` sellado con una `significance` distinta a la del
		registry: el sello dejó de contar la verdad.
	3. WARN  `refine/` existe pero vacío. El camino legacy crea el directorio
		antes de escribir: vacío = no hubo ideas, o alguien barrió las que
		había. Se revisa a mano; con `--strict` cuenta como fallo.
	4. INFO  `annotate/` existe pero sin notas: la fase corrió y no extrajo ideas
		(sesión floja o gate). No es fallo; se cuenta para verlo.

Alcance: por defecto solo sesiones selladas desde `ANNOTATE_PHASE_ERA`
(2026-10-30, cuando nació `--phase`). Antes de esa fecha no existía la rama
rota y el legado sellaba sin `annotate/` por diseño. Las sesiones legacy con
notas en `refine/` quedan fuera de la firma 1: sí produjeron memoria.

Uso:
	python scripts/audit_memento_silent_loss.py
	python scripts/audit_memento_silent_loss.py --since 2026-10-01
	python scripts/audit_memento_silent_loss.py --json
	python scripts/audit_memento_silent_loss.py --strict   # los WARN fallan

Salida: 0 limpio · 1 hallazgos · 2 error de entorno.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

ANNOTATE_PHASE_ERA = "2026-10-30"


def _index_significance(index_file: Path):
	if not index_file.exists():
		return None
	for line in index_file.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
		stripped = line.strip()
		if stripped.startswith("significance:"):
			try:
				return float(stripped.split(":", 1)[1].strip())
			except ValueError:
				return None
	return None


def audit(since: str) -> dict:
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry

	root = get_memento_root()
	registry = MementoRegistry()
	fails = []
	warns = []
	zero_notes = []
	scanned = 0
	skipped_pre_era = 0
	for source, sessions in registry.state.get("registry", {}).items():
		if not isinstance(sessions, dict):
			continue
		for session_id, entry in sessions.items():
			agentic = entry.get("agentic")
			dir_rel = entry.get("dir")
			if not agentic or not dir_rel:
				continue
			distilled_at = str(agentic.get("distilled_at") or "")
			if distilled_at < since:
				skipped_pre_era += 1
				continue
			base = root / dir_rel
			if not base.is_dir():
				fails.append({"check": "missing_dir", "source": source, "session": session_id, "dir": dir_rel, "distilled_at": distilled_at})
				continue
			scanned += 1
			annotate_dir = base / "annotate"
			notes = list(annotate_dir.glob("*.md")) if annotate_dir.is_dir() else []
			refine_dir = base / "refine"
			refines = list(refine_dir.glob("*.md")) if refine_dir.is_dir() else []

			sealed = agentic.get("annotate_pending") is False and agentic.get("hash") == entry.get("memento_hash")
			annotate_ran = annotate_dir.is_dir()
			if sealed and not annotate_ran and not refines:
				# La rama rota NUNCA crea `annotate/`; si el directorio existe, la
				# fase de notas corrió (aunque no extrajera nada) y no es esta firma.
				fails.append(
					{
						"check": "sealed_without_notes",
						"source": source,
						"session": session_id,
						"dir": dir_rel,
						"distilled_at": distilled_at,
						"max_significance": agentic.get("max_significance"),
					}
				)
			elif sealed and annotate_ran and not notes:
				# Informativo: annotate corrió y no extrajo ideas (sesión floja o
				# gate). No es fallo, pero conviene verlo.
				zero_notes.append({"source": source, "session": session_id, "dir": dir_rel})

			index_sig = _index_significance(base / "memento" / "index.md")
			registry_sig = agentic.get("max_significance")
			if index_sig is not None and registry_sig is not None and round(float(index_sig), 2) != round(float(registry_sig), 2):
				fails.append(
					{
						"check": "index_registry_mismatch",
						"source": source,
						"session": session_id,
						"dir": dir_rel,
						"index_significance": index_sig,
						"registry_significance": registry_sig,
					}
				)

			if refine_dir.is_dir() and not refines:
				warns.append({"check": "empty_refine_dir", "source": source, "session": session_id, "dir": dir_rel})

	return {
		"root": str(root),
		"since": since,
		"scanned": scanned,
		"skipped_pre_era": skipped_pre_era,
		"fails": fails,
		"warns": warns,
		"zero_notes": zero_notes,
	}


def main() -> None:
	parser = argparse.ArgumentParser(description="Auditoría read-only de pérdidas silenciosas en Memento")
	parser.add_argument("--since", default=ANNOTATE_PHASE_ERA, metavar="ISO", help=f"Solo sesiones selladas desde esta fecha (default: {ANNOTATE_PHASE_ERA}, nacimiento de --phase)")
	parser.add_argument("--json", action="store_true", help="Salida JSON")
	parser.add_argument("--strict", action="store_true", help="Los WARN también fallan")
	args = parser.parse_args()

	try:
		report = audit(args.since)
	except Exception as e:  # entorno roto ≠ hallazgo: no confundir al watchdog
		print(f"[audit] error de entorno: {e}", file=sys.stderr)
		sys.exit(2)

	if args.json:
		print(json.dumps(report, indent=2, ensure_ascii=False))
	else:
		print(f"[audit] root={report['root']}")
		print(f"[audit] desde {report['since']}: {report['scanned']} sesiones selladas auditadas ({report['skipped_pre_era']} fuera de alcance)")
		for item in report["fails"]:
			print(f"  FAIL {item['check']}: {item['session']} ({item['dir']})")
		for item in report["warns"]:
			print(f"  WARN {item['check']}: {item['session']} ({item['dir']})")
		if report["zero_notes"]:
			print(f"  INFO {len(report['zero_notes'])} sesión(es) con annotate ejecutado y 0 notas (revisar rutas/gate)")
		print(f"[audit] {len(report['fails'])} fallo(s), {len(report['warns'])} aviso(s)")

	if report["fails"] or (args.strict and report["warns"]):
		sys.exit(1)


if __name__ == "__main__":
	main()
