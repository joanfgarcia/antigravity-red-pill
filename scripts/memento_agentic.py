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
import json
import logging
import os
import sys
import time
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


def _write_run_state(stats: dict) -> None:
	"""Persiste la producción del pase agéntico (best-effort).

	El `sleep/finalize` del nightly lee `static_ascended` de aquí para que el
	resumen del ciclo no oculte lo que Memento SÍ ingresó (las ascensiones
	estáticas no pasan por las fases de metabolismo). Sin fichero o ilegible, el
	finalize simplemente lo omite.
	"""
	try:
		from red_pill.core.paths import get_state_dir

		payload = {
			"ran_at": time.time(),
			"processed": int(stats.get("processed", 0) or 0),
			"failed": int(stats.get("failed", 0) or 0),
			"would_ingest": int(stats.get("would_ingest", 0) or 0),
			"static_ascended": int(stats.get("static_ascended", 0) or 0),
		}
		path = get_state_dir() / "memento_agentic_state.json"
		tmp = path.with_suffix(path.suffix + ".tmp")
		tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
		tmp.replace(path)
	except Exception as e:  # nunca romper el pase por telemetría
		logger.warning(f"No se pudo escribir el estado del pase agéntico: {e}")


def main() -> None:
	parser = argparse.ArgumentParser(description="Memento agentic pass: Distill → Refine (shadow gate)")
	parser.add_argument("--limit", type=int, default=None, help="Max sessions this run (default: MEMENTO_AGENTIC_NIGHT_LIMIT)")
	parser.add_argument("--heal-stale", action="store_true", help="Process only stale sessions (Healer branch, no limit)")
	parser.add_argument("--force", action="store_true", help="Re-process sessions already distilled on disk (ignore the crash-recovery mark)")
	parser.add_argument(
		"--only-long",
		type=int,
		default=None,
		metavar="CHARS",
		help="Re-distill only sessions whose largest work unit exceeds CHARS (re-process sessions truncated by the old model window; use with --force)",
	)
	parser.add_argument(
		"--redistill-round",
		type=str,
		default=None,
		metavar="ISO",
		help="Inicio de la ronda de re-destilación (ISO): con --force, SOLO reprocesa las sesiones con distilled_at anterior a la ronda — reanudación sin repetir lo ya re-procesado (watchdog, 2026-09-15)",
	)
	parser.add_argument("--shadow-report", action="store_true", help="Print the shadow-gate summary and exit")
	parser.add_argument(
		"--target",
		metavar="SOURCE:ID",
		help="Procesar UNA sesión concreta (SOURCE:session_id), ignorando pending_agentic. Sin checkpoint global (el progreso lo lleva el job DAG fan-out).",
	)
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
	pending = pending_agentic(registry, root=root, force=args.force, redistill_since=args.redistill_round)
	# --only-long: quedarse solo con las sesiones cuyo work unit más largo excede
	# el umbral (las truncadas por la ventana del modelo anterior). Requiere --force
	# para que pending_agentic incluya las ya destiladas.
	if args.only_long is not None:
		from red_pill.memento.agentic import session_max_work_unit_chars

		before = len(pending)
		pending = [
			(src, sid, r) for src, sid, r in pending if session_max_work_unit_chars(root, registry.get(src, sid).get("dir", "")) > args.only_long
		]
		logger.info(f"[--only-long {args.only_long}] {len(pending)}/{before} sesiones superan el umbral.")
	if args.target:
		source, _, sid = args.target.partition(":")
		if not source or not sid:
			parser.error("--target debe ser SOURCE:session_id")
		targets = [(source, sid)]
	elif args.heal_stale:
		targets = [(source, session_id) for source, session_id, reason in pending if reason == "stale"]
	else:
		limit = args.limit if args.limit is not None else int(getattr(cfg, "MEMENTO_AGENTIC_NIGHT_LIMIT", 20))
		# stale primero (line refs muertos duelen más que secciones ausentes)
		ordered = sorted(pending, key=lambda t: t[2] != "stale")
		targets = [(source, session_id) for source, session_id, _reason in ordered[:limit]]

	if not targets:
		logger.info("Agentic pass: nothing pending.")
		_write_run_state({"processed": 0, "failed": 0, "would_ingest": 0, "static_ascended": 0})
		return
	if not llm_available():
		logger.warning("Local LLM not available — agentic pass deferred to next cycle.")
		_write_run_state({"processed": 0, "failed": 0, "would_ingest": 0, "static_ascended": 0})
		return

	# Con --target el progreso lo lleva el checkpoint del job DAG fan-out, no el
	# global de la ronda: run_agentic no escribe checkpoint del progress.
	cp = None if args.target else _checkpoint_path()
	stats = run_agentic(root, registry, targets, http_transport, checkpoint_path=cp, redistill_since=args.redistill_round)
	registry.save()
	logger.info(
		f"Agentic pass complete: {stats['processed']} session(s) distilled+refined, "
		f"{stats['failed']} failed, shadow would-ingest {stats['would_ingest']}/{stats['processed']}, "
		f"static ascensions {stats.get('static_ascended', 0)}."
	)
	_write_run_state(stats)
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
