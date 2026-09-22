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

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import prompts, runtime
from .fragments import _as_list, _frontmatter_block, _work_units, slugify_title

logger = logging.getLogger(__name__)

_SCORE_BATCH = 20

_FEMININE_JOAN = re.compile(
	r"\bJoan\b[^.\n]{0,60}\b(abrumada|emocionada|cansada|preocupada|contenta|enfadada|orgullosa|nerviosa|tranquila|feliz|harta)\b", re.I
)
_IDENTITY_CONFUSION = re.compile(r"\b(Samantha|Cenicienta)\b", re.I)
_THIRD_PERSON = re.compile(r"(^|\b)(Aleth|El asistente|La asistente)\s+(ha|había|fue|es|utiliza|propone|explica|implementa|crea|rectifica)\b", re.I)
_IMPERSONAL = re.compile(
	r"^\s*(se\s+(creó|omitió|implementó|generó|corrigió|configuró|eliminó|añadió|actualizó|desplegó|sincronizó|ejecutó|arregló|restauró))\b", re.I
)
_ALETH_PAST = re.compile(
	r"\bAleth\s+(creó|implementó|propuso|explicó|desplegó|configuró|generó|corrigió|añadió|actualizó|sincronizó|ejecutó|arregló|restauró|omitió)\b", re.I
)
_FIRST_PERSON = re.compile(
	r"\b(me|mi|mis|nos|le|les|he|creé|implementé|propuso|expliqué|dije|hice|desplegué|generé|corregí|configuré|actualicé|sincronicé|ejecuté|arreglé|restauré)\b",
	re.I,
)


def is_first_person(text: str) -> bool:
	"""True si la nota tiene marcadores de 1ª persona (criterio del rewrite)."""
	return bool(_FIRST_PERSON.search(text))


def quality_flags(text: str) -> List[str]:
	"""Detectores MEM-006 P2: género femenino de Joan, identidad confundida, voz 3ª."""
	flags: List[str] = []
	if _FEMININE_JOAN.search(text):
		flags.append("gender")
	if _IDENTITY_CONFUSION.search(text):
		flags.append("identity")
	if _THIRD_PERSON.search(text) or _IMPERSONAL.search(text) or _ALETH_PAST.search(text):
		flags.append("voice")
	return flags


def _normalize(text: str) -> str:
	return re.sub(r"[^a-z0-9áéíóúüñ ]+", " ", text.lower()).strip()


def _tokens(text: str) -> set:
	return set(re.findall(r"[a-záéíóúüñ]{4,}", text.lower()))


def _rank(a: Dict[str, Any]) -> Tuple[int, float, int]:
	flags = a.get("flags") or []
	voice_ok = 0 if "voice" in flags else 1
	try:
		sig = float(a.get("significance") or 0)
	except (TypeError, ValueError):
		sig = 0.0
	return (voice_ok, sig, len(str(a.get("text") or "")))


def dedup_annotations(annotations: List[Dict[str, Any]], threshold: float = 0.6) -> List[Dict[str, Any]]:
	"""P1-A: colapsa duplicados exactos (hash normalizado) y near-dups (tokens).

	Conserva la mejor variante: 1ª persona > significance > longitud. Los gemelos
	work/social del mismo evento se funden aquí.
	"""
	kept: List[Dict[str, Any]] = []
	kept_tokens: List[set] = []
	seen: set = set()
	for a in sorted(annotations, key=_rank, reverse=True):
		text = str(a.get("text") or "")
		h = hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()
		if h in seen:
			continue
		t = _tokens(text + " " + str(a.get("title") or ""))
		if any(t and kt and len(t & kt) / min(len(t), len(kt)) > threshold for kt in kept_tokens):
			continue
		seen.add(h)
		kept.append(a)
		kept_tokens.append(t)
	return kept


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


def _extract(transport: runtime.Transport, content: str) -> List[Dict[str, Any]]:
	ideas: List[Dict[str, Any]] = []
	for system, template in ((prompts.ANNOTATE_WORK_SYSTEM, prompts.ANNOTATE_WORK_USER), (prompts.ANNOTATE_SOCIAL_SYSTEM, prompts.ANNOTATE_SOCIAL_USER)):
		prompt = template.format(identity=prompts.IDENTITY_BIO, voice=prompts._VOICE_RULE, fragment=content)
		raw = transport(system, prompt, 1024)
		for idea in runtime._extract_json_array(raw) or []:
			if not isinstance(idea, dict):
				continue
			text = str(idea.get("text") or "").strip()
			if not text:
				continue
			ideas.append(
				{
					"title": str(idea.get("title") or "Anotación")[:80],
					"text": text,
					"significance": idea.get("significance"),
					"emotion": str(idea.get("emotion") or "gray"),
					"intensity": idea.get("intensity"),
					"theme": str(idea.get("theme") or ""),
					"relics": [str(r) for r in _as_list(idea.get("relics"))][:4],
				}
			)
	return ideas


def rewrite_voice_notes(transport: runtime.Transport, annotations: List[Dict[str, Any]], batch_size: int = 10) -> int:
	"""Re-escribe en 1ª persona las notas que no lo están (MEM-006 Q8, lever b).

	Reintenta con lotes decrecientes hasta individual (el modelo responde a veces
	solo una parte). Actualiza `text` y recalcula `flags` in-place. Devuelve cuántas
	se reescribieron.
	"""
	rewritten = 0
	for size in (batch_size, 4, 1):
		pending = [a for a in annotations if not is_first_person(str(a.get("text") or ""))]
		if not pending:
			break
		for start in range(0, len(pending), size):
			chunk = pending[start : start + size]
			listing = "\n\n".join(f"[{i}] {a['text'][:600]}" for i, a in enumerate(chunk))
			raw = transport(prompts.VOICE_REWRITE_SYSTEM, prompts.VOICE_REWRITE_USER.format(identity=prompts.IDENTITY_BIO, notes=listing), 2048)
			for row in runtime._extract_json_array(raw) or []:
				if not isinstance(row, dict):
					continue
				raw_idx = row.get("i")
				if raw_idx is None:
					continue
				try:
					idx = int(raw_idx)
				except (TypeError, ValueError):
					continue
				new_text = str(row.get("text") or "").strip()
				if 0 <= idx < len(chunk) and new_text:
					chunk[idx]["text"] = new_text
					chunk[idx]["flags"] = quality_flags(new_text)
					rewritten += 1
	return rewritten


def _score_dual(transport: runtime.Transport, annotations: List[Dict[str, Any]]) -> None:
	"""Puntúa cada anotación en los ejes work/social con reintento por lotes decrecientes.

	El lote grande puede truncarse por contexto (500 → recorte del transporte) y el
	modelo responde solo una parte: los no puntuados se reintentan en lotes menores
	hasta individual. Los que aun así queden sin puntuar se marcan `unscored`.
	"""
	for batch_size in (_SCORE_BATCH, 5, 1):
		pending = [a for a in annotations if "work_score" not in a]
		if not pending:
			return
		for start in range(0, len(pending), batch_size):
			chunk = pending[start : start + batch_size]
			listing = "\n\n".join(f"[{i}] {a['text'][:400]}" for i, a in enumerate(chunk))
			raw = transport(prompts.DUAL_SCORE_SYSTEM, prompts.DUAL_SCORE_USER.format(memories=listing), 2048)
			for row in runtime._extract_json_array(raw) or []:
				if not isinstance(row, dict):
					continue
				raw_idx = row.get("i")
				if raw_idx is None:
					continue
				try:
					idx = int(raw_idx)
					work = max(0.0, min(1.0, float(row.get("work_score", 0.0) or 0.0)))
					social = max(0.0, min(1.0, float(row.get("social_score", 0.0) or 0.0)))
				except (TypeError, ValueError):
					continue
				if 0 <= idx < len(chunk):
					chunk[idx]["work_score"] = work
					chunk[idx]["social_score"] = social


def _distill_ref(root: Path, dir_rel: str, nnn: str) -> str:
	files = sorted((root / dir_rel / "distill").glob(f"{nnn}-*.md"))
	return str(files[0].relative_to(root)) if files else ""


def annotate_session(
	root: Path,
	dir_rel: str,
	session_id: str,
	source: str,
	transport: runtime.Transport,
	voice_rewrite: Optional[bool] = None,
) -> float:
	"""Anota una sesión desde el RAW → `annotate/NNN-<slug>.md`. Devuelve la max significance.

	Los ficheros de anotación llevan el sello de ascensión preservado por fichero
	(stem) para que re-anotar sea idempotente. `voice_rewrite` (None → cfg) re-escribe
	en 1ª persona las notas que no lo están antes de puntuar.
	"""
	import red_pill.config as cfg

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
		if pfm.get("ascended") == "true":
			prev_seals[prev.stem] = {
				"ascended": True,
				"ascended_at": pfm.get("ascended_at"),
				"ascended_to": pfm.get("ascended_to"),
				"ascended_point_id": pfm.get("ascended_point_id"),
			}
	for stale in annotate_dir.glob("*.md"):
		stale.unlink()

	annotations: List[Dict[str, Any]] = []
	units = _work_units(root / dir_rel)
	for nnn, ref, content in units:
		for idea in _extract(transport, content):
			idea["split_ref"] = ref
			idea["nnn"] = nnn
			idea["flags"] = quality_flags(idea["text"])
			annotations.append(idea)

	annotations = dedup_annotations(annotations)
	if voice_rewrite:
		rewrite_voice_notes(transport, annotations)
	_score_dual(transport, annotations)

	max_significance = 0.0
	route_count: Dict[str, int] = {"work": 0, "social": 0, "none": 0}
	flag_count: Dict[str, int] = {}
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
		(annotate_dir / f"{a['nnn']}-{slug}.md").write_text(f"{refine_fm}\n\n{a['text']}\n", encoding="utf-8")
	meta = {
		"session_id": session_id,
		"source": source,
		"annotated_at": datetime.now(timezone.utc).isoformat(),
		"engine": runtime.engine_id(),
		"annotate_prompt_version": runtime.annotate_prompt_version(),
		"voice_rewrite": bool(voice_rewrite),
		"splits": len(units),
		"notas": len(annotations),
		"max_significance": round(max_significance, 2),
		"routes": route_count,
		"flags": flag_count,
	}
	meta_tmp = (annotate_dir / "_meta.json").with_suffix(".json.tmp")
	meta_tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
	meta_tmp.replace(annotate_dir / "_meta.json")
	from red_pill.memento.record import update_session_record

	update_session_record(root, dir_rel, "annotate", meta)
	return max_significance
