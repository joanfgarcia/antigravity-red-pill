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

from red_pill.memento.agentic.selection import select_targets  # noqa: E402  (tras insertar src en sys.path)


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
		# 2026-11-27: el estado era la única evidencia del pase y decía
		# `failed: 0` tras 60 pasos fallidos por VRAM. Si el pase se difiere, el
		# motivo viaja aquí (y al log); el finalize del sueño no oculta el porqué.
		if stats.get("aborted_llm_down"):
			payload["deferred"] = True
			payload["reason"] = str(stats.get("defer_reason") or "llm_unavailable")[:500]
		elif int(stats.get("failed", 0) or 0) > 0:
			payload["deferred"] = False
			payload["reason"] = f"{stats['failed']} fallo(s) no ambientales"
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
	parser.add_argument(
		"--phase",
		choices=("distill", "annotate"),
		default=None,
		help="Ejecutar SOLO una fase del pase (2026-10-30). Cada fase puede servirse de un modelo distinto (task distill / annotate): intercaladas por sesión cuestan DOS cambios de modelo por sesión; por fases, dos por corrida. Sin este flag, el pase hace las dos por sesión (comportamiento histórico). `annotate` exige MEMENTO_ANNOTATE_FROM_RAW=true (con OFF no hay fase de notas; se rechaza en arranque).",
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

	# E-97e9d2 (2026-11-19): la fase de notas ES la rama annotate; con el flag OFF
	# no hay nada que correr (refine legacy exige destilar en la misma corrida).
	# Antes el proceso arrancaba, "procesaba" cada sesión sin escribir nota y sin
	# fallar — un nocturno podía completar el ciclo entero sin producir memoria.
	if args.phase == "annotate" and not bool(getattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", False)):
		parser.error(
			"--phase annotate requiere MEMENTO_ANNOTATE_FROM_RAW=true: con OFF no hay fase de "
			"notas (refine legacy solo corre sin --phase, con las secciones destiladas en la "
			"misma corrida)."
		)

	registry = MementoRegistry()
	if args.shadow_report:
		print(_shadow_report(registry))
		return

	root = get_memento_root()
	pending = pending_agentic(
		registry, root=root, force=args.force, redistill_since=args.redistill_round, phase=args.phase
	)
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
		msg_limit = int(getattr(cfg, "MEMENTO_AGENTIC_NIGHT_MSG_LIMIT", 3000))
		# Misma política que el `discover` del DAG (agentic/selection.py): stale primero,
		# dos presupuestos (sesiones + mensajes) y `limit=0` = sin tope de verdad.
		# NB-001 F5: con el cost model ON y `--phase`, el presupuesto variable pasa a
		# la divisa de la fase (chars en distill; unidades+notas en annotate).
		chosen = select_targets(pending, limit, msg_limit=msg_limit, registry=registry, phase=args.phase, root=root)
		targets = [(source, session_id) for source, session_id, _reason in chosen]

	if not targets:
		logger.info("Agentic pass: nothing pending.")
		_write_run_state({"processed": 0, "failed": 0, "would_ingest": 0, "static_ascended": 0})
		return
	if not llm_available():
		logger.warning("Local LLM not available — agentic pass deferred to next cycle.")
		_write_run_state(
			{
				"processed": 0,
				"failed": 0,
				"would_ingest": 0,
				"static_ascended": 0,
				"aborted_llm_down": True,
				"defer_reason": "llm_available()=false (/v1/models no responde)",
			}
		)
		# Mismo contrato que el resto del pase: aplazar, no fingir éxito.
		import os

		sys.exit(int(os.environ.get("RP_DEFER_EXIT_CODE", "77")))

	# Con --target el progreso lo lleva el checkpoint del job DAG fan-out, no el
	# global de la ronda: run_agentic no escribe checkpoint del progress.
	cp = None if args.target else _checkpoint_path()
	stats = run_agentic(
		root,
		registry,
		targets,
		http_transport,
		checkpoint_path=cp,
		redistill_since=args.redistill_round,
		phase=args.phase,
	)
	registry.save()
	logger.info(
		f"Agentic pass complete [{args.phase or 'both'}]: {stats['processed']} session(s) processed, "
		f"{stats.get('skipped_distill', 0)} skipped (sin polaroids), "
		f"{stats.get('skipped_annotate_disabled', 0)} skipped (annotate con flag OFF), "
		f"{stats['failed']} failed, shadow would-ingest {stats['would_ingest']}/{stats['processed']}, "
		f"static ascensions {stats.get('static_ascended', 0)}."
	)
	_write_run_state(stats)
	# Deferral declarativo (regla job_dag_execution, 2026-09-08): si el LLM local
	# se cayó (3+ fallos consecutivos de conexión, o UNO en el fan-out de una
	# sola sesión) o no se procesó nada porque el modelo no se pudo cargar
	# (503/VRAM), salimos con código de defer para que el DAG marque la etapa
	# aplazada y el runner la reintente — NO es un error del trabajo.
	#
	# 2026-11-27 (ciclo 8a315ef2): sin `RP_DEFER_EXIT_CODE` el script salía 0
	# («salida limpia») y el DAG reportaba `success` con 60 pasos sin producir
	# memoria. El código por defecto (77) es el mismo que usan los demás pases
	# (memento_annotate, memento_validate); las etapas de `chronicle.yaml`
	# declaran `defer_exit_code: 77` para que el driver lo convierta en JobDeferred.
	if stats.get("aborted_llm_down"):
		import os

		defer_code = int(os.environ.get("RP_DEFER_EXIT_CODE", "77"))
		logger.warning(
			f"LLM local no disponible ({stats.get('defer_reason') or 'sin motivo'}) — "
			f"saliendo con defer_exit_code={defer_code} para que el ciclo se aplaza."
		)
		sys.exit(defer_code)
	# Fallo real (contenido, disco): no fingir éxito. La etapa queda `failed`
	# con su motivo; con `on_fail: warn` el DAG sigue y la evidencia se guarda.
	if stats["processed"] == 0 and stats["failed"] > 0:
		logger.error(f"{stats['failed']} sesión(es) fallidas sin progreso y sin causa ambiental — salida 1.")
		sys.exit(1)


if __name__ == "__main__":
	main()
