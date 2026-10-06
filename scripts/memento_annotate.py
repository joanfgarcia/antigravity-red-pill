#!/usr/bin/env python3
"""memento_annotate.py — rebuild de anotaciones (MEM-006) sobre el árbol Memento.

QUÉ ES
	Ejecuta la etapa `annotate` sobre el árbol real, sesión a sesión: anotaciones
	idea-level extraídas del RAW (una sola compresión), con Bio de identidad (P0),
	dedup P1-A (hash + tokens), gate de calidad (género/identidad → no asciende),
	routing dual con zona muerta y rewrite de voz en 1ª persona.

PARA QUÉ
	Rebuild tras el fix del clasificador y la migración al modelo de anotaciones:
	reemplaza los `refine/` (re-resúmenes del summary, 52% duplicados de cuerpo) por
	`annotate/` (notas únicas, ≤600, voz de Aleth). La ascensión posterior sube los
	engramas (work/social) con `dual_route` + ejes.

HISTORIA (por qué nació)
	Sesión 2026-09-22 (MEM-006 + RFC-003). El diagnóstico midió: 9.424 refines con
	solo 4.556 cuerpos únicos; el refine leía summaries de distill (doble compresión)
	y producía re-resúmenes; el clasificador puntuaba textos compuestos (centro
	inestable). Los pilotos mostraron que anotar desde el raw corrige longitud
	(>600: 7,5%→~1,7%), duplicados (16,1%→1,9%) y, con el paso de rewrite, la voz
	(36%→100% 1ª persona en 5 sesiones). Evidencia en MEM-006 §6 (desk).

USO
	uv run python scripts/memento_annotate.py --status           # control: anotadas/stale/pendientes/errores + notas
	uv run python scripts/memento_annotate.py --list             # sesiones pendientes (JSON)
	uv run python scripts/memento_annotate.py --list --all       # ignora la frescura
	RP_ELEMENT='{"dir": "..."}' uv run python scripts/memento_annotate.py --from=score --reason "umbrales nuevos"
	# re-puntúa sin re-extraer (MEM-009)
	uv run python scripts/memento_annotate.py                    # procesa RP_ELEMENT (job)
	uv run python scripts/memento_annotate.py --root /tmp/x      # árbol alternativo (pruebas)

	Job: `configs/jobs/memento_annotate_rebuild.yaml` (element_job, checkpoint por
	sesión, pausable/reanudable). Control del rebuild: `--status` lee el **meta por
	sesión** (`annotate/_meta.json`: annotated_at, annotate_prompt_version, engine,
	voice_rewrite, splits, notas, routes, flags) — una sesión con meta de la versión
	vigente se considera anotada y se omite (idempotente y reanudable).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from red_pill.memento import get_memento_root
from red_pill.memento.agentic import annotate_prompt_version, http_transport
from red_pill.memento.agentic.annotate import annotate_session


def _sessions(root: Path) -> list:
	dirs = sorted({p.parent.parent for p in root.rglob("memento/index.md")})
	out = []
	for d in dirs:
		rel = d.relative_to(root)
		if len(rel.parts) >= 3:
			out.append(str(rel))
	return out


def _current_engine() -> str:
	"""Motor servido actual (mismo origen que el sello `engine` de `_meta.json`)."""
	try:
		from red_pill.memento.agentic import runtime

		return str(runtime.engine_id() or "").strip()
	except Exception:
		return ""


def _gate_enabled() -> bool:
	"""MEM-010 F2 (RULE 4, default OFF): gating previo en `--list`/`--status`."""
	import red_pill.config as cfg

	return bool(getattr(cfg, "MEMENTO_ANNOTATE_GATE", False))


def _run_id(pipeline: dict) -> str:
	"""Identidad estable de una ola de gating (manifest vigente) — MEM-010 F2b.

	Estable entre re-invocaciones de `--list` (defer → re-list): el upsert por
	`run_id` del historial depende de ello. F3 (ledger) podrá refinarla con ids
	de job sin romper este contrato."""
	return f"r-{str(pipeline.get('manifest_hash') or '')[:12]}"


def _gate_sweep(root: Path) -> list:
	"""Recorre las sesiones, evalúa y sella el gate; devuelve los elementos a emitir."""
	from red_pill.memento import gating

	pipeline = gating.current_pipeline()
	run_id = _run_id(pipeline)
	engine = _current_engine() or None
	elements = []
	for d in _sessions(root):
		result = gating.gate_session(root, d, run_id=run_id, pipeline=pipeline, engine=engine)
		if result.get("emit"):
			elements.append({"dir": d, "action": result["action"]})
	return elements


def _fresh(root: Path, dir_rel: str, engine_aware: bool = False) -> bool:
	"""Frescura por meta de sesión: `annotate/_meta.json` con el prompt_version vigente.

	Con `engine_aware`, una sesión anotada por OTRO motor también es stale — el
	rebuild pineado re-anota las anotaciones del modelo equivocado (auditoría
	adversarial 2026-09-23). Si el motor actual no se puede resolver, no se
	marca stale (conservador).
	"""
	meta = root / dir_rel / "annotate" / "_meta.json"
	if not meta.exists():
		return False
	try:
		data = json.loads(meta.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return False
	if data.get("annotate_prompt_version") != annotate_prompt_version():
		return False
	if engine_aware:
		current = _current_engine()
		if current and str(data.get("engine") or "") != current:
			return False
	return True


def pending(root: Path, force: bool = False, stale_engine: bool = False) -> list:
	return [d for d in _sessions(root) if force or not _fresh(root, d, engine_aware=stale_engine)]


def status(root: Path) -> dict:
	"""Control del rebuild: anotadas (versión vigente) / stale / pendientes / errores."""
	current = annotate_prompt_version()
	current_engine = _current_engine()
	out = {
		"prompt_version": current,
		"engine": current_engine,
		"sesiones": 0,
		"anotadas": 0,
		"stale": 0,
		"stale_engine": 0,
		"pendientes": 0,
		"errores": 0,
		"notas": 0,
		"ultima": "",
	}
	for d in _sessions(root):
		out["sesiones"] += 1
		meta = root / d / "annotate" / "_meta.json"
		if not meta.exists():
			out["stale" if list((root / d / "annotate").glob("*.md")) else "pendientes"] += 1
			continue
		try:
			data = json.loads(meta.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			out["errores"] += 1
			continue
		if data.get("annotate_prompt_version") == current:
			out["anotadas"] += 1
			out["notas"] += int(data.get("notas") or 0)
			out["ultima"] = max(out["ultima"], str(data.get("annotated_at") or ""))
			if current_engine and str(data.get("engine") or "") != current_engine:
				out["stale_engine"] += 1
		else:
			out["stale"] += 1
	return out


def _canonical_ids() -> dict:
	"""dir_rel → session_id canónico (del registry); evita escribir ids derivados de la ruta."""
	from red_pill.memento.registry import MementoRegistry

	mapping: dict = {}
	for _source, sessions in (MementoRegistry().state.get("registry") or {}).items():
		if not isinstance(sessions, dict):
			continue
		for sid, entry in sessions.items():
			dir_rel = str((entry or {}).get("dir") or "")
			if dir_rel:
				mapping[dir_rel] = sid
	return mapping


def process_one(
	root: Path,
	dir_rel: str,
	force: bool = False,
	stale_engine: bool = False,
	from_phase: Optional[str] = None,
	reason: Optional[str] = None,
	action: Optional[str] = None,
) -> dict:
	# MEM-010 F2b: un elemento emitido por el GATE (action definida) no pasa por
	# el atajo legacy `_fresh` — el gate ya decidió; `rescore` entra por `score`.
	if action is not None and action != "process" and not from_phase:
		from_phase = "score" if action == "rescore" else None
	# `--from` implica reproceso (MEM-009 §2.1): apuntar a una fase hecha la re-ejecuta.
	if action is None and not force and not from_phase and _fresh(root, dir_rel, engine_aware=stale_engine):
		return {"dir": dir_rel, "skipped": "fresh"}
	if force:
		# `--all` = fuerza total desde cero: borra el parcial (con `--from`, el
		# prerrequisito sale entonces de las notas materializadas, no del parcial).
		(root / dir_rel / "annotate" / "_partial.json").unlink(missing_ok=True)
	parts = Path(dir_rel).parts
	source = parts[1] if len(parts) > 1 else "unknown"
	session_id = _canonical_ids().get(dir_rel) or (parts[2] if len(parts) > 2 else dir_rel)
	run_id = None
	if action is not None:
		from red_pill.memento import gating

		run_id = _run_id(gating.current_pipeline())
	try:
		max_sig = annotate_session(root, dir_rel, session_id, source, http_transport, voice_rewrite=True, from_phase=from_phase, reason=reason)
	except Exception as e:
		if run_id is not None:
			from red_pill.memento import gating
			from red_pill.memento.agentic.runner import _is_llm_connection_error

			if not _is_llm_connection_error(e):
				gating.mark_outcome(root, dir_rel, run_id=run_id, state="failed", outcome={"error": str(e)[:512]})
		raise
	n = len(list((root / dir_rel / "annotate").glob("*.md")))
	if run_id is not None:
		from red_pill.memento import gating

		gating.mark_outcome(root, dir_rel, run_id=run_id, state="done", outcome={"status": "ok", "notas": n})
	return {"dir": dir_rel, "anotaciones": n, "max_significance": round(float(max_sig), 2)}


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--list", action="store_true", help="Imprime las sesiones pendientes (JSON).")
	parser.add_argument("--status", action="store_true", help="Control del rebuild: anotadas/stale/pendientes/errores y notas.")
	parser.add_argument("--all", action="store_true", help="Ignora la frescura (re-anota todo).")
	parser.add_argument(
		"--stale-engine",
		action="store_true",
		help="Re-anota también las sesiones cuyo motor difiere del actual (p. ej. las anotadas con tiny_aya).",
	)
	parser.add_argument(
		"--from",
		dest="from_phase",
		choices=("extract", "rewrite", "score"),
		default=None,
		help="Entra al pipeline en esa fase reutilizando el estado persistido (parcial o notas); degrada con aviso si faltan prerrequisitos.",
	)
	parser.add_argument("--reason", default=None, help="Motivo de la invocación (audit trail en _meta.json).")
	parser.add_argument("--gate-migrate", action="store_true", help="Migración one-shot (MEM-010 F2b): completa manifest/métricas en metas legacy adoptables.")
	parser.add_argument("--dry-run", action="store_true", help="Con --gate-migrate: solo censo, sin escribir.")
	parser.add_argument("--root", type=Path, default=None, help="Raíz Memento (default: la configurada).")
	args = parser.parse_args()
	root = args.root or get_memento_root()

	if args.status:
		out = status(root)
		if _gate_enabled():
			from red_pill.memento import gating

			pipeline = gating.current_pipeline()
			actions: dict = {}
			reasons: dict = {}
			for d in _sessions(root):
				latest = (gating.read_gate(root, d).get("latest") or {})
				if latest.get("to_fingerprint") == pipeline["manifest_hash"]:
					key = str(latest.get("action") or "?")
					actions[key] = actions.get(key, 0) + 1
					if key == "skip":
						reason = str(latest.get("reason") or "?")
						reasons[reason] = reasons.get(reason, 0) + 1
			out["gate"] = {"acciones": actions, "motivos_skip": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:10])}
		print(json.dumps(out, indent=2, ensure_ascii=False))
		return
	if args.gate_migrate:
		from red_pill.memento import gating

		pipeline = gating.current_pipeline()
		stats: dict = {"fresh": 0, "adopted": 0, "legacy-unknown": 0, "sin-meta": 0, "error": 0}
		for d in _sessions(root):
			try:
				result = gating.migrate_session(root, d, pipeline=pipeline, write=not args.dry_run)
			except Exception:
				result = "error"
			stats[result] = stats.get(result, 0) + 1
		print(json.dumps({"dry_run": bool(args.dry_run), **stats}, ensure_ascii=False, indent=2))
		return
	if args.list:
		if _gate_enabled():
			print(json.dumps(_gate_sweep(root), ensure_ascii=False))
			return
		print(json.dumps([{"dir": d} for d in pending(root, force=args.all, stale_engine=args.stale_engine)], ensure_ascii=False))
		return
	raw = os.environ.get("RP_ELEMENT")
	if not raw:
		print("RP_ELEMENT no definido (usa el job element_job) o pasa --list")
		sys.exit(2)
	el = json.loads(raw)
	try:
		res = process_one(
			root,
			str(el["dir"]),
			force=args.all,
			stale_engine=args.stale_engine,
			from_phase=args.from_phase,
			reason=args.reason,
			action=el.get("action"),
		)
	except Exception as e:
		from red_pill.memento.agentic.runner import _is_llm_connection_error

		if _is_llm_connection_error(e):
			print(f"[DEFER] LLM no disponible: {e}")
			sys.exit(int(os.environ.get("RP_DEFER_EXIT_CODE", 77)))
		raise
	print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
	main()
