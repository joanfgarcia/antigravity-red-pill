"""Etapa annotate (MEM-006): anotaciones desde el RAW, una sola compresión.

A diferencia del refine legacy (que leía summaries de distill y producía
re-resúmenes), annotate lee el fragmento crudo (`memento/NNN-*.md`) y materializa
cada idea como texto propio. Incluye:
- P0: Bio de identidad (`prompts.IDENTITY_BIO`) — voz/género anclados.
- P1-A: dedup de anotaciones (hash normalizado + solape de tokens).
- Gate de calidad (detectores de MEM-006 P2): género/identidad → no asciende.
- Routing dual (work/social) con zona muerta: margen < δ → `unstable` (no asciende; queda en el árbol para re-scoring futuro).

Se activa con `MEMENTO_ANNOTATE_FROM_RAW` (RULE 4, default OFF); con OFF el pase
sigue usando `refine_session` legacy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import prompts, runtime
from .annotation_phases import (  # noqa: F401  (re-exported: tests/agents use annotate.<phase>)
	_distill_ref,
	_extract,
	_needs_voice_rewrite,
	_score_dual,
	_with_annotate_task,
	dedup_post_rewrite,
	rewrite_voice_notes,
)
from .annotation_quality import (
	compute_note_metrics,
	dedup_annotations,
	is_first_person,  # noqa: F401  (re-exported via red_pill.memento.agentic)
	looks_english,  # noqa: F401  (re-exported for tests)
	quality_flags,
)
from .annotation_state import (
	_PARTIAL,
	PHASES,
	_annotations_from_notes,
	_contract,
	_empty_partial,
	_load_partial,
	_resolve_from,
	_save_partial,
	_scrub_idea,
)
from .fragments import _frontmatter_block, fragment_view, slugify_title, work_units

logger = logging.getLogger(__name__)


# ── MEM-010 F1: métricas por sesión para el gating (RFC §3.2) ────────────────
# Se computan SIEMPRE sobre las notas FINALES (post rewrite/dedup) y con el
# umbral de dedup efectivo guardado junto a la métrica, para que vivo y
# backfill comparen like-for-like (enmienda r3 del panel).


def session_input_hash(root: Path, dir_rel: str, units: List[Any]) -> Tuple[Optional[str], str]:
	"""Hash normativo de la ENTRADA de la sesión (MEM-010 §3.3) + su fuente.

	Camino normativo: `compute_hash(extract_body(memento/index.md))` — el MISMO
	cómputo que el `memento_hash` del render (§4.5.1). Fallback defensivo para
	árboles sin index (no ocurre en el árbol real): digest estable de las
	unidades leídas, con fuente distinguible para el gate.
	"""
	import hashlib

	from red_pill.memento.render import compute_hash, extract_body

	index = root / dir_rel / "memento" / "index.md"
	if index.exists():
		return compute_hash(extract_body(index.read_text(encoding="utf-8"))), "index"
	if not units:
		return None, "none"
	payload = "\x1e".join(f"{u.key}:{compute_hash(u.content)}" for u in units)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest(), "units"


def _route(work: float, social: float, th_work: float, th_social: float, dead_zone: float) -> Optional[str]:
	"""Ruta por ejes con zona muerta: margen < δ → None (unstable, no asciende)."""
	over_w = work >= th_work
	over_s = social >= th_social
	if over_w and over_s:
		d_work = work - th_work
		d_social = social - th_social
		if abs(d_work - d_social) < dead_zone:
			return None
		route = "work" if d_work > d_social else "social"
		return route if max(d_work, d_social) >= dead_zone else None
	if over_w:
		return "work" if (work - th_work) >= dead_zone else None
	if over_s:
		return "social" if (social - th_social) >= dead_zone else None
	return None


def annotate_session(
	root: Path,
	dir_rel: str,
	session_id: str,
	source: str,
	transport: runtime.Transport,
	voice_rewrite: Optional[bool] = None,
	from_phase: Optional[str] = None,
	reason: Optional[str] = None,
) -> float:
	"""Anota una sesión desde el RAW → `annotate/NNN-<slug>.md`. Devuelve la max significance.

	Los ficheros de anotación llevan el sello de ascensión preservado por fichero
	(stem) para que re-anotar sea idempotente. `voice_rewrite` (None → cfg) re-escribe
	en 1ª persona las notas que no lo están antes de puntuar.

	MEM-009 F1 — reanudable: nada se borra al empezar; `annotate/_partial.json`
	checkpointa cada split extraído (keyed por rango de mensajes, revalidado por
	`content_hash`) y cada fase (extract/rewrite/score). Un kill pierde como mucho
	un split. Al completar se materializan notas + `_meta.json`, se borran las notas
	huérfanas y el parcial. `from_phase` (extract|rewrite|score) re-ejecuta desde esa
	fase reutilizando el estado persistido de las anteriores (parcial o notas).
	"""
	import red_pill.config as cfg
	from red_pill.core.progress import report_stage_progress
	from red_pill.memento.render import compute_hash

	# 2026-09-24: contrato propio de annotate (ver `_with_annotate_task`).
	transport = _with_annotate_task(transport)

	th_work = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_WORK", 0.6))
	th_social = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE_SOCIAL", 0.5))
	dead_zone = float(getattr(cfg, "MEMENTO_ANNOTATE_DEAD_ZONE", 0.05))
	if voice_rewrite is None:
		voice_rewrite = bool(getattr(cfg, "MEMENTO_ANNOTATE_VOICE_REWRITE", False))
	annotate_dir = root / dir_rel / "annotate"
	annotate_dir.mkdir(parents=True, exist_ok=True)

	prev_seals: Dict[str, Dict[str, Any]] = {}
	for prev in annotate_dir.glob("*.md"):
		try:
			from red_pill.memento.ascension import parse_refine as _parse_refine

			pfm, _ = _parse_refine(prev.read_text(encoding="utf-8"))
		except Exception:
			continue
		ascended_raw = pfm.get("ascended")
		ascended = ascended_raw if isinstance(ascended_raw, bool) else str(ascended_raw).strip().lower() == "true"
		if ascended:
			prev_seals[prev.stem] = {
				"ascended": True,
				"ascended_at": pfm.get("ascended_at"),
				"ascended_to": pfm.get("ascended_to"),
				"ascended_point_id": pfm.get("ascended_point_id"),
			}

	contract = _contract(voice_rewrite)
	partial = _load_partial(annotate_dir, contract)
	entry, prior = _resolve_from(from_phase, partial, _annotations_from_notes(annotate_dir, contract) if from_phase else None, voice_rewrite)

	units = work_units(root / dir_rel)
	if entry == "extract":
		if from_phase == "extract":
			partial = _empty_partial(contract)  # --from=extract: todo desde cero
		keys = [unit.key for unit in units]
		fresh_splits: Dict[str, Any] = {}
		reused = extracted = 0
		for i_unit, unit in enumerate(units, 1):
			report_stage_progress(label="extract", current=i_unit, total=len(units), session=session_id)
			key, nnn, ref, content = unit.key, unit.nnn, unit.ref, unit.content
			chash = compute_hash(content)
			saved = partial["splits"].get(key)
			if saved and saved.get("status") == "extracted" and saved.get("content_hash") == chash:
				saved["nnn"] = nnn
				saved["split_ref"] = ref
				for idea in saved.get("ideas") or []:
					idea["split_ref"], idea["nnn"] = ref, nnn
				fresh_splits[key] = saved
				reused += 1
				continue
			ideas = []
			view_mode, operator_label, agent_label = runtime.fragment_view_settings()
			for idea in _extract(transport, fragment_view(content, view_mode, operator_label, agent_label)):
				idea = _scrub_idea(idea)
				idea["split_ref"] = ref
				idea["nnn"] = nnn
				idea["flags"] = quality_flags(idea["text"])
				ideas.append(idea)
			fresh_splits[key] = {"nnn": nnn, "split_ref": ref, "content_hash": chash, "status": "extracted", "ideas": ideas}
			# Rangos desaparecidos se descartan: solo sobreviven los de este run.
			partial["splits"] = {k: v for k, v in partial["splits"].items() if k in keys}
			partial["splits"][key] = fresh_splits[key]
			partial["phases"] = {ph: "pending" for ph in PHASES}
			_save_partial(annotate_dir, partial)
			extracted += 1
		if reused:
			logger.info("annotate %s: %d splits reanudados del parcial, %d extraídos", dir_rel, reused, extracted)
		ordered = [idea for key in keys if key in fresh_splits for idea in fresh_splits[key]["ideas"]]
		if extracted or partial["phases"]["extract"] != "done":
			annotations = dedup_annotations([dict(i) for i in ordered], threshold=runtime.memento_dedup_threshold())
			partial["splits"] = fresh_splits
			partial["annotations"] = annotations
			partial["phases"] = {"extract": "done", "rewrite": "pending", "score": "pending"}
			_save_partial(annotate_dir, partial)
		else:
			annotations = partial["annotations"]
	else:
		annotations = prior or []
		partial["annotations"] = annotations
		partial["phases"] = {"extract": "done", "rewrite": "pending" if entry == "rewrite" else "done", "score": "pending"}
		if entry == "score":
			for a in annotations:
				a.pop("work_score", None)
				a.pop("social_score", None)
		_save_partial(annotate_dir, partial)

	if voice_rewrite and partial["phases"]["rewrite"] != "done":
		rewrite_voice_notes(transport, annotations)
		partial["phases"]["rewrite"] = "done"
		_save_partial(annotate_dir, partial)
	if bool(getattr(cfg, "MEMENTO_ANNOTATE_POST_REWRITE_DEDUP", False)) and partial["phases"]["score"] != "done":
		# Idempotente: re-ejecutarla sobre una lista ya deduplicada no cambia nada.
		deduped = dedup_post_rewrite(annotations, float(getattr(cfg, "MEMENTO_ANNOTATE_EMBED_DEDUP_THRESHOLD", 0.90)))
		if len(deduped) != len(annotations):
			logger.info("annotate %s: dedup post-rewrite %d → %d notas", dir_rel, len(annotations), len(deduped))
			annotations = deduped
			partial["annotations"] = annotations
			_save_partial(annotate_dir, partial)
	if partial["phases"]["score"] != "done":
		if entry != "score" and partial["phases"]["rewrite"] == "done" and voice_rewrite:
			# El rewrite cambia el texto: un score previo ya no vale.
			for a in annotations:
				a.pop("work_score", None)
				a.pop("social_score", None)
		_score_dual(transport, annotations)
		partial["phases"]["score"] = "done"
		_save_partial(annotate_dir, partial)

	max_significance = 0.0
	route_count: Dict[str, int] = {"work": 0, "social": 0, "none": 0}
	flag_count: Dict[str, int] = {}
	written: set = set()
	for a in annotations:
		work = float(a.get("work_score", 0.0) or 0.0)
		social = float(a.get("social_score", 0.0) or 0.0)
		flags = sorted(set(a["flags"]) | ({"unscored"} if "work_score" not in a else set()))
		route = None if ({"gender", "identity"} & set(flags)) else _route(work, social, th_work, th_social, dead_zone)
		route_count[route or "none"] += 1
		for fl in flags:
			flag_count[fl] = flag_count.get(fl, 0) + 1
		significance = round(max(work, social), 2)
		max_significance = max(max_significance, significance)
		slug = slugify_title(a["title"])
		seal = prev_seals.get(f"{a['nnn']}-{slug}", {})
		refine_fm = _frontmatter_block(
			[
				("session_id", session_id),
				("source", source),
				("source_lines", a["split_ref"]),
				("split_ref", a["split_ref"]),
				("distill_ref", _distill_ref(root, dir_rel, a["nnn"])),
				("title", a["title"]),
				("significance", significance),
				("emotion", a["emotion"]),
				("intensity", float(a.get("intensity") or 0.0)),
				("texture", {"theme": a["theme"], "relics": a["relics"]}),
				("work_score", round(work, 2)),
				("social_score", round(social, 2)),
				("dual_route", route if route else "none"),
				("quality_flags", flags),
				("engine", runtime.engine_id()),
				("prompt_version", runtime.annotate_prompt_version()),
				("ascended", bool(seal.get("ascended", False))),
				("ascended_at", seal.get("ascended_at")),
				("ascended_to", seal.get("ascended_to")),
				("ascended_point_id", seal.get("ascended_point_id")),
			]
		)
		name = f"{a['nnn']}-{slug}.md"
		(annotate_dir / name).write_text(f"{refine_fm}\n\n{a['text']}\n", encoding="utf-8")
		written.add(name)
	input_hash, input_hash_source = session_input_hash(root, dir_rel, units)
	meta = {
		"session_id": session_id,
		"source": source,
		"annotated_at": datetime.now(timezone.utc).isoformat(),
		"engine": runtime.engine_id(),
		"annotate_prompt_version": runtime.annotate_prompt_version(),
		# Sanitizado (MEM-009 §3.4): nunca la ruta absoluta del operador.
		"identity_bio_source": Path(str(prompts.IDENTITY_BIO_SOURCE)).name if prompts.IDENTITY_BIO_SOURCE else prompts.IDENTITY_BIO_SOURCE,
		"voice_rewrite": bool(voice_rewrite),
		"splits": len(units),
		"notas": len(annotations),
		"max_significance": round(max_significance, 2),
		"routes": route_count,
		"flags": flag_count,
		# Audit trail (MEM-009 §2.1): umbrales efectivos + punto de entrada + motivo.
		"thresholds": {"work": th_work, "social": th_social, "dead_zone": dead_zone},
		"from_phase": entry if from_phase else None,
		"from_requested": from_phase,
		"reason": reason,
		# MEM-010 F1: manifest + métricas + identidad de entrada (gating).
		"manifest": runtime.annotate_manifest(),
		"manifest_hash": runtime.annotate_manifest_hash(),
		"metrics": compute_note_metrics(annotations, dedup_threshold=runtime.memento_dedup_threshold()),
		"input_hash": input_hash,
		"input_hash_source": input_hash_source,
	}
	from red_pill.memento.record import write_json_atomic

	write_json_atomic(annotate_dir / "_meta.json", meta)
	# Solo tras el `_meta` verificado: huérfanos fuera y parcial plegado.
	for stale in annotate_dir.glob("*.md"):
		if stale.name not in written:
			stale.unlink()
	(annotate_dir / _PARTIAL).unlink(missing_ok=True)
	from red_pill.memento.record import update_session_record

	update_session_record(root, dir_rel, "annotate", meta)
	return max_significance
