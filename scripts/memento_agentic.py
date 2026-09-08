#!/usr/bin/env python3
"""
memento_agentic.py — Pase agéntico Distill → Refine sobre el árbol Memento (RFC-002 §4.5, Fase 3.5).

Procesa sesiones renderizadas sin destilar (o con distill stale tras un
re-render) usando el LLM local (Samantha vía EdgeEngine). El gate de curación
corre EN SOMBRA (§4.6): calcula would-ingest, sella `significance` y lo cuenta
en el registry — el archivo Qdrant no cambia hasta la Fase 4.

Usage:
	uv run python scripts/memento_agentic.py                  # delta nocturno (límite de config)
	uv run python scripts/memento_agentic.py --limit 5        # acotar el lote
	uv run python scripts/memento_agentic.py --heal-stale     # solo sesiones stale (rama del Healer)
	uv run python scripts/memento_agentic.py --shadow-report  # resumen del gate en sombra
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("memento_agentic")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _shadow_report(registry) -> str:
	entries = [
		(source, session_id, entry["agentic"])
		for source, sessions in registry.state["registry"].items()
		for session_id, entry in sessions.items()
		if entry.get("agentic")
	]
	if not entries:
		return "Gate en sombra: sin sesiones destiladas aún."
	would = sum(1 for _s, _i, a in entries if a.get("gate_would_ingest"))
	lines = [
		f"Gate en sombra (§4.6): {len(entries)} sesiones destiladas, would-ingest {would} ({would * 100 // len(entries)}%).",
		"Por fuente:",
	]
	per_source = {}
	for source, _sid, agentic in entries:
		total, ingest = per_source.get(source, (0, 0))
		per_source[source] = (total + 1, ingest + int(agentic.get("gate_would_ingest", False)))
	for source, (total, ingest) in sorted(per_source.items()):
		lines.append(f"  {source}: {ingest}/{total}")
	return "\n".join(lines)


def _checkpoint_path() -> Optional[Path]:
	"""Checkpoint del modo bounded: lo inyecta el ScriptJobDriver como RP_CHECKPOINT_FILE."""
	raw = os.environ.get("RP_CHECKPOINT_FILE")
	return Path(raw) if raw else None


def main() -> None:
	parser = argparse.ArgumentParser(description="Memento agentic pass: Distill → Refine (shadow gate)")
	parser.add_argument("--limit", type=int, default=None, help="Max sessions this run (default: MEMENTO_AGENTIC_NIGHT_LIMIT)")
	parser.add_argument("--heal-stale", action="store_true", help="Process only stale sessions (Healer branch, no limit)")
	parser.add_argument("--force", action="store_true", help="Re-process sessions already distilled on disk (ignore the crash-recovery mark)")
	parser.add_argument("--shadow-report", action="store_true", help="Print the shadow-gate summary and exit")
	args = parser.parse_args()

	import red_pill.config as cfg
	from red_pill.memento import get_memento_root
	from red_pill.memento.agentic import http_transport, llm_available, pending_agentic, run_agentic
	from red_pill.memento.registry import MementoRegistry

	registry = MementoRegistry()
	if args.shadow_report:
		print(_shadow_report(registry))
		return

	root = get_memento_root()
	pending = pending_agentic(registry, root=root, force=args.force)
	if args.heal_stale:
		targets = [(source, session_id) for source, session_id, reason in pending if reason == "stale"]
	else:
		limit = args.limit if args.limit is not None else int(getattr(cfg, "MEMENTO_AGENTIC_NIGHT_LIMIT", 20))
		# stale primero (line refs muertos duelen más que secciones ausentes)
		ordered = sorted(pending, key=lambda t: t[2] != "stale")
		targets = [(source, session_id) for source, session_id, _reason in ordered[:limit]]

	if not targets:
		logger.info("Agentic pass: nothing pending.")
		return
	if not llm_available():
		logger.warning("Local LLM not available — agentic pass deferred to next cycle.")
		return

	stats = run_agentic(root, registry, targets, http_transport, checkpoint_path=_checkpoint_path())
	registry.save()
	logger.info(
		f"Agentic pass complete: {stats['processed']} session(s) distilled+refined, "
		f"{stats['failed']} failed, shadow would-ingest {stats['would_ingest']}/{stats['processed']}."
	)
	# Deferral declarativo (regla job_dag_execution, 2026-09-08): si el LLM local
	# se cayó (3+ fallos consecutivos de conexión) o no se procesó nada por LLM
	# caído, salir con RP_DEFER_EXIT_CODE para que el driver marque JobDeferred y
	# el runner lo reintente cuando el recurso se libere — NO es un error del job.
	if stats.get("aborted_llm_down") or (stats["processed"] == 0 and stats["failed"] > 0):
		import os

		defer_code = os.environ.get("RP_DEFER_EXIT_CODE")
		if defer_code:
			logger.warning(f"LLM local no disponible (0 procesadas, {stats['failed']} falladas) — saliendo con defer_exit_code={defer_code}")
			sys.exit(int(defer_code))
		logger.warning("LLM local no disponible y sin RP_DEFER_EXIT_CODE definido — salida limpia (0 procesadas).")


if __name__ == "__main__":
	main()
