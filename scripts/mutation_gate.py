#!/usr/bin/env python3
"""Gate de mutación: cada guard tiene que MORDER.

Los paneles adversariales encontraron tres veces el mismo defecto de clase: tests
que pasaban igual con el guard quitado. Eso no es criterio, es un check que
falta. Este script rompe cada guard en el fichero real, corre los tests que lo
protegen y exige que **fallen**. Si alguno sigue verde, el guard no está cubierto.

Uso:
.venv/bin/python scripts/mutation_gate.py [--only NOMBRE]

Exit code 1 si alguna mutación sobrevive.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTEST = [str(REPO / ".venv" / "bin" / "python"), "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"]


@dataclass(frozen=True)
class Mutation:
	name: str
	file: str
	original: str
	mutated: str
	tests: tuple[str, ...]
	why: str


MUTATIONS: tuple[Mutation, ...] = (
	Mutation(
		name="rama-con-hojas",
		file="src/red_pill/metabolism/maintenance.py",
		original="if members_by_hub.get(str(hub.id), 0) > 0:",
		mutated="if False and members_by_hub.get(str(hub.id), 0) > 0:",
		tests=("tests/test_olv_001_branch_keeps_leaves.py",),
		why="una rama con hojas no puede erosionarse (D-01)",
	),
	Mutation(
		name="reaper-con-hojas",
		file="src/red_pill/metabolism/forgetting.py",
		original="if members.get(str(hub.id), 0) > 0:",
		mutated="if False and members.get(str(hub.id), 0) > 0:",
		tests=("tests/test_olv_001_final_guards.py::test_reaper_never_deletes_a_branch_with_leaves",),
		why="el reaper no borra una rama con hojas (I-01)",
	),
	Mutation(
		name="transicion-legacy",
		file="src/red_pill/metabolism/forgetting.py",
		original="and len(raw_stamps) < 2",
		mutated="and False",
		tests=("tests/test_olv_001_final_guards.py::test_legacy_with_two_recalls_promotes_instead_of_dying",),
		why="2+ recuperaciones sin historia entran al circuito largo (§8.2)",
	),
	Mutation(
		name="gracia-d16",
		file="src/red_pill/metabolism/forgetting.py",
		original="since = min(real_since, grace)",
		mutated="since = real_since",
		tests=("tests/test_olv_001_final_guards.py::test_active_day_counter_changes_the_verdict",),
		why="la migración no cobra un histórico truncado (D-16)",
	),
	Mutation(
		name="washout-permastore",
		file="src/red_pill/metabolism/maintenance.py",
		original='if payload.get("immune") or payload.get("permastore"):',
		mutated='if payload.get("immune"):',
		tests=("tests/test_olv_001_final_guards.py::test_washout_does_not_delete_and_respects_permastore",),
		why="el washout no puntúa un congelado (D-10)",
	),
	Mutation(
		name="alcance-colecciones",
		file="src/red_pill/metabolism/forgetting.py",
		original='if collection not in LADDER_COLLECTIONS:\n\t\treturn "keep"',
		mutated='if False:\n\t\treturn "keep"',
		tests=("tests/test_olv_001_final_guards.py::test_unknown_collection_is_never_decided",),
		why="directivas y alma tienen gobierno propio",
	),
	Mutation(
		name="cli-seco-por-defecto",
		file="src/red_pill/cli.py",
		original="if not apply:",
		mutated="if False:",
		tests=("tests/test_cli_unit.py::test_cli_main_erode",),
		why="`erode` sin --apply no puede borrar (D-22)",
	),
	Mutation(
		name="ceguera-huerfanos",
		file="src/red_pill/memory.py",
		original='if _live:\n\t\t\t\tstructural_exclusions.append(models.FieldCondition(key="hub_id", match=models.MatchAny(any=sorted(_live))))',
		mutated='if False:\n\t\t\t\tstructural_exclusions.append(models.FieldCondition(key="hub_id", match=models.MatchAny(any=sorted(_live))))',
		tests=("tests/test_olv_001_blindness_and_cap.py::test_orphan_member_is_recallable_again",),
		why="un marcador con padre inexistente no puede quedar ciego",
	),
	Mutation(
		name="tope-sesiones",
		file="src/red_pill/metabolism/hub_synthesis.py",
		original="if limit_sessions is not None and processed >= limit_sessions:",
		mutated="if limit_sessions is not None and groups and list(groups).index(session_id) >= limit_sessions:",
		tests=("tests/test_olv_001_blindness_and_cap.py::test_limit_sessions_counts_synthesised_sessions",),
		why="el cupo se gasta en sesiones sintetizadas, no en la posición",
	),
)


def _run(tests: tuple[str, ...]) -> int:
	proc = subprocess.run(PYTEST + list(tests), cwd=str(REPO), capture_output=True, text=True, timeout=900)
	return proc.returncode


def _check(mutation: Mutation) -> tuple[bool, str]:
	target = REPO / mutation.file
	fd, backup_name = tempfile.mkstemp(suffix=".bak")
	Path(backup_name).write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
	try:
		source = target.read_text(encoding="utf-8")
		if mutation.original not in source:
			return False, "NO-ENCONTRADO"
		target.write_text(source.replace(mutation.original, mutation.mutated, 1), encoding="utf-8")
		code = _run(mutation.tests)
	finally:
		target.write_text(Path(backup_name).read_text(encoding="utf-8"), encoding="utf-8")
		Path(backup_name).unlink(missing_ok=True)
	if code == 0:
		return False, "SOBREVIVE"
	return True, "muerde"


def main() -> int:
	ap = argparse.ArgumentParser(description="Cada guard tiene que morder (RFC-OLV-001)")
	ap.add_argument("--only", help="Ejecutar solo la mutación con este nombre")
	args = ap.parse_args()

	selected = [m for m in MUTATIONS if not args.only or m.name == args.only]
	if not selected:
		print(f"no hay mutación con nombre {args.only!r}", file=sys.stderr)
		return 2

	print(f"{'guard':<26} {'veredicto':<14} por qué")
	failures = 0
	for m in selected:
		ok, verdict = _check(m)
		print(f"{m.name:<26} {verdict:<14} {m.why}")
		if not ok:
			failures += 1
	if failures:
		print(f"\n{failures} guard(s) SIN COBERTURA: un test que no muerde no es un test.")
		return 1
	print(f"\nLos {len(selected)} guards muerden: quitar cualquiera rompe su test.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
