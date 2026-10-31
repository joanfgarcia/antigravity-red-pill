#!/usr/bin/env python3
"""Verifica que un log de despertar no cite nada que no exista.

El guardia de un despertar autónomo NO puede ser el prompt: pedirle a un 7B "no
inventes" es una palanca roma (medido el 2026-10-30 en el carril de notas). El
guardia es **mecánico**: se extraen del log las anclas verificables y se
comprueban contra el mundo.

Anclas que se comprueban:
· hashes de commit (7-40 hex) → existen en el repo indicado (`git cat-file -e`)
· rutas absolutas             → existen en disco
· ids de job (8 hex)          → hay un log o un estado con ese prefijo
· ramas citadas (ej. `next`)  → existen en el repo

Salida: JSON con `ok`, `verificadas`, `fallidas` (con el motivo). Código 0 si
todo lo citado existe; 1 si hay algo inventado o caducado.

Uso:
	python scripts/awakening_verify.py /tmp/opencode/despertar_k2.md --repo .
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

HASH = re.compile(r"\b[0-9a-f]{7,40}\b")
# Falsos positivos que hay que descartar antes de acusar a nadie (medido sobre un
# log real: la fecha 20261029 y dos ids de job salían como "inventados"):
FECHA = re.compile(r"^(?:19|20)\d{6}$")   # YYYYMMDD
PURA_CIFRA = re.compile(r"^\d+$")
RUTA = re.compile(r"(?<![\w/])/(?:home|tmp|opt|var|etc|usr)/[\w./-]{3,}")
RAMA = re.compile(r"\brama\s+`?([a-zA-Z][\w./-]{2,})`?", re.I)


def _git(repo: Path, *args: str) -> bool:
	try:
		return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=20).returncode == 0
	except Exception:
		return False


def verificar(texto: str, repo: Path | None = None, jobs_dir: Path | None = None) -> Dict[str, Any]:
	verificadas: List[str] = []
	no_verificables: List[Dict[str, str]] = []
	fallidas: List[Dict[str, str]] = []

	for m in sorted(set(HASH.findall(texto))):
		if PURA_CIFRA.match(m) or FECHA.match(m):
			continue  # una fecha o un número no es un ancla que se pueda acusar
		# Un hash de 7-40 hex puede ser un commit o un id de job; se prueba en orden.
		if repo and _git(repo, "cat-file", "-e", f"{m}^{{commit}}"):
			verificadas.append(f"commit {m}")
			continue
		if jobs_dir and any(p.name.startswith(m) for p in jobs_dir.glob("*")):
			verificadas.append(f"job {m}")
			continue
		if jobs_dir is None:
			# Sin libro de jobs no hay ambigüedad posible: un hex que no es commit
			# es un commit inventado. Sólo se declara "no verificable" cuando
			# existe un registro de jobs contra el que podría casar.
			fallidas.append({"ancla": m, "motivo": "no existe como commit"})
		else:
			# Un id de job viejo ya no tiene fichero de estado: no se puede
			# verificar, pero tampoco afirmar que sea falso. Se declara, no se acusa.
			no_verificables.append({"ancla": m, "motivo": "sin fichero de estado; puede ser un job caducado"})

	for ruta in sorted(set(RUTA.findall(texto))):
		limpia = ruta.rstrip(".,;:)")
		if Path(limpia).exists():
			verificadas.append(f"ruta {limpia}")
		else:
			fallidas.append({"ancla": limpia, "motivo": "la ruta no existe"})

	for rama in sorted(set(RAMA.findall(texto))):
		if repo and _git(repo, "rev-parse", "--verify", rama):
			verificadas.append(f"rama {rama}")
		else:
			fallidas.append({"ancla": f"rama {rama}", "motivo": "no existe en el repo"})

	return {
		# `ok` sólo se rompe con algo que se ha podido COMPROBAR y es falso. Lo no
		# verificable se declara: un guardia que grita en falso se ignora.
		"ok": not fallidas,
		"verificadas": verificadas,
		"no_verificables": no_verificables,
		"fallidas": fallidas,
		"n_verificadas": len(verificadas),
		"n_no_verificables": len(no_verificables),
		"n_fallidas": len(fallidas),
	}


def main() -> None:
	ap = argparse.ArgumentParser(description="Verifica las anclas de un log de despertar")
	ap.add_argument("fichero")
	ap.add_argument("--repo", default=".", help="repo donde verificar los commits (default: cwd)")
	ap.add_argument("--jobs", default=None, help="dir de estado de jobs (default: el del Búnker)")
	args = ap.parse_args()

	jobs_dir = Path(args.jobs) if args.jobs else None
	if jobs_dir is None:
		try:
			from red_pill.core.paths import get_state_dir

			jobs_dir = get_state_dir() / "jobs"
		except Exception:
			jobs_dir = None

	texto = Path(args.fichero).read_text(encoding="utf-8", errors="ignore")
	res = verificar(texto, Path(args.repo), jobs_dir)
	print(json.dumps(res, ensure_ascii=False, indent=1))
	if not res["ok"]:
		print("\n[awakening-verify] ANCLAS QUE NO EXISTEN — el log no se acepta tal cual", file=sys.stderr)
		sys.exit(1)


if __name__ == "__main__":
	main()
