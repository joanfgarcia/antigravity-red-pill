#!/usr/bin/env python3
"""Generic IDE injection dispatcher.

Scans scripts/inject/<ide>/ for detect.py + inject.py adapters and runs
them.  This is the SINGLE entry-point called by install_neo.sh and
upgrade.sh — those scripts never need to be modified when adding a new IDE.

Usage:
	python scripts/inject_cli.py --redpill-dir /path/to/red-pill [--uv-path /path/to/uv]
	python scripts/inject_cli.py --list                    # show discovered adapters
	python scripts/inject_cli.py --ide opencode --remove   # remove red-pill from one IDE
	python scripts/inject_cli.py --check                   # audita la convivencia; no escribe

Cada siembra va envuelta en una auditoría (``inject/_audit.py``): foto de lo que
puede tocar y hallazgos de convivencia ANTES, y diff + hallazgos DESPUÉS, con
copia de lo anterior en ``$XDG_DATA_HOME/red-pill/state/inject/<fecha>/``. La
siembra convive con otros arneses y con la mano del Operador: quien actualiza
(humano o agente) tiene que ver qué había y qué cambió.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("inject_cli")

# Ensure the inject package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inject import _audit as audit  # noqa: E402
from inject._registry import detect_present, discover_adapters, inject_all, precheck_all  # noqa: E402

_RULE = "─" * 72


def _banner(title: str, body: str) -> None:
	print(f"\n{_RULE}\n{title}\n{_RULE}\n{body}", flush=True)


def _run_check(workspace: str | None) -> int:
	findings = audit.audit(workspace)
	_banner("red-pill · auditoría de convivencia (sólo lectura)", audit.format_findings(findings))
	return 1 if any(f.level == audit.ERROR for f in findings) else 0


def _audited_inject(args, adapters) -> int:
	"""Siembra con foto antes/después. Nunca bloquea: avisa y deja el informe."""
	run_dir = audit.new_run_dir()
	before = audit.snapshot(args.workspace)
	audit.save_snapshot(before, os.path.join(run_dir, "before"))
	pre = audit.audit(args.workspace)
	_banner(
		"red-pill · ANTES de sembrar — revisa la convivencia",
		audit.format_findings(pre) + f"\n  copia de lo actual en {run_dir}/before",
	)

	total = inject_all(args, adapters)

	after = audit.snapshot(args.workspace)
	post = audit.audit(args.workspace)
	changes = audit.diff(before, after)
	report = audit.write_report(run_dir, pre, post, changes)
	audit.prune_runs()
	errors = sum(1 for f in post if f.level == audit.ERROR)
	warns = sum(1 for f in post if f.level == audit.WARN)
	_banner(
		"red-pill · DESPUÉS de sembrar — revisa los cambios",
		"Ficheros cambiados:\n"
		+ audit.summarize_changes(changes)
		+ "\nHallazgos:\n"
		+ audit.format_findings(post)
		+ f"\n\n  Informe con el diff completo: {report}"
		+ "\n  Si otro arnés o una config tuya convive con estos ficheros, comprueba que sigue funcionando."
		+ (f"\n  ✗ {errors} error(es) y {warns} aviso(s) requieren atención." if errors or warns else ""),
	)
	return total


def main():
	parser = argparse.ArgumentParser(description="Red Pill IDE injection dispatcher.")
	parser.add_argument("--redpill-dir", help="Path to Red Pill source directory.")
	parser.add_argument("--uv-path", help="Path to uv binary.")
	parser.add_argument("--workspace", help="Workspace root (for project-scoped configs).")
	parser.add_argument("--update", action="store_true", help="Force-update anchor blocks.")
	parser.add_argument("--no-backup", action="store_true", help="Skip .bak backups.")
	parser.add_argument("--remove", action="store_true", help="Remove red-pill from target IDE(s).")
	parser.add_argument("--list", action="store_true", help="List discovered adapters and exit.")
	parser.add_argument("--ide", help="Target a specific IDE (csv). Default: auto-detect all present.")
	parser.add_argument(
		"--profile",
		default="full",
		help="Perfil de arnés `rol:capacidad:egress` (p.ej. worker:local-9b:none) o `full` (por defecto). Ver configs/profiles/.",
	)
	parser.add_argument("--dry-run", action="store_true", help="Resuelve el perfil y muestra el plan sin escribir nada.")
	parser.add_argument("--check", action="store_true", help="Audita la convivencia con otros arneses/configs y sale (1 si hay errores). No escribe.")
	args = parser.parse_args()

	if args.check:
		sys.exit(_run_check(args.workspace))

	adapters = discover_adapters()

	if args.list:
		print("Discovered IDE adapters:")
		for a in adapters:
			present = a.detect_mod.detect(args.workspace)
			status = "PRESENT" if present else "absent"
			print(f"  {a.name:20s} [{status}]")
		return

	if args.ide:
		target_names = [n.strip() for n in args.ide.split(",")]
		adapters = [a for a in adapters if a.name in target_names]
		if not adapters:
			logger.error(f"No adapter found for: {args.ide}")
			sys.exit(1)
	else:
		adapters = detect_present(args.workspace)

	if not adapters:
		logger.info("No present IDEs detected. Nothing to inject.")
		return

	# Hard gate: an adapter may require a minimum runtime (OpenCode v2). Run
	# before any write so an install/update on a legacy IDE fails loudly.
	if not args.remove:
		failures = precheck_all(adapters, args.workspace)
		if failures:
			for name, message in failures:
				logger.error(f"{name}: {message}")
			logger.error("Aborting: this Red Pill release requires the supported runtime (OpenCode v2).")
			sys.exit(3)

	logger.info(f"Targeting: {', '.join(a.name for a in adapters)}")
	if args.dry_run:
		_banner("red-pill · ANTES de sembrar (dry-run) — revisa la convivencia", audit.format_findings(audit.audit(args.workspace)))
	if args.dry_run or args.remove:
		total = inject_all(args, adapters)
	else:
		total = _audited_inject(args, adapters)
	logger.info(f"Done. {total} block(s) modified across {len(adapters)} IDE(s).")


if __name__ == "__main__":
	main()
