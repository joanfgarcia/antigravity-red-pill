#!/usr/bin/env python3
"""memento_rebuild_run.py — lanza la remediación de un run del ledger (MEM-010 F3).

QUÉ ES
	Helper de lanzamiento: construye un `element_job` cuyo `elements_command` es
	`memento_annotate.py --rebuild-run <run_id> [--actions ...]` (re-sella el
	subconjunto como `forced` y emite la lista congelada) y lo envía al manager.

USO
	uv run python scripts/memento_rebuild_run.py <run_id> [--actions processed,failed]
	[--reason "por qué"] [--priority 3] [--dry-run]

	`--dry-run` imprime el payload del job sin enviarlo (revisión humana).
"""

from __future__ import annotations

import argparse
import json
import subprocess


def build_payload(run_id: str, actions: str, reason: str | None, priority: int) -> dict:
	"""Payload del element_job de remediación (testable sin tocar el manager)."""
	elements_command = f"uv run python scripts/memento_annotate.py --rebuild-run {run_id} --actions {actions}"
	if reason:
		elements_command += f" --reason {json.dumps(reason)}"
	return {
		"title": f"Memento remediación run {run_id}",
		"mission_id": "memento-rebuild-remediation",
		"source": "element_job",
		"priority": priority,
		"step_command": "uv run python scripts/memento_annotate.py",
		"elements_command": elements_command,
		"defer_exit_code": 77,
		"llm": {"task": "annotate", "model": "granite_8b", "device_fallback": ["gpu"]},
		"preflight": {"llm_required": True, "min_free_vram_mb": 7600},
		"control": {"max_step_minutes": 40},
	}


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("run_id", help="run_id original del ledger (ver --runs)")
	parser.add_argument("--actions", default="all", help="processed,skipped,failed,all (CSV)")
	parser.add_argument("--reason", default=None, help="Motivo (queda en el gate y el ledger)")
	parser.add_argument("--priority", type=int, default=3)
	parser.add_argument("--dry-run", action="store_true", help="Imprime el payload sin enviarlo")
	args = parser.parse_args()

	payload = build_payload(args.run_id, args.actions, args.reason, args.priority)
	if args.dry_run:
		print(json.dumps(payload, ensure_ascii=False, indent=2))
		return
	subprocess.run(
		["uv", "run", "red-pill", "job", "submit", "--source", "element_job", "--payload", json.dumps(payload)],
		check=True,
	)
	print(json.dumps({"submitted": True, "run_id": args.run_id, "actions": args.actions}, ensure_ascii=False))


if __name__ == "__main__":
	main()
