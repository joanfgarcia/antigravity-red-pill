"""Annotate partial-state machinery — contract/partial save/load and `--from`
resolution. Split from annotate.py (SHARD-PS-04); IO-bound to the annotate dir.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import runtime
from .annotation_quality import quality_flags
from .fragments import _as_list

logger = logging.getLogger(__name__)


_PARTIAL = "_partial.json"


PHASES = ("extract", "rewrite", "score")


_SCRUB_FIELDS = ("title", "text", "theme", "emotion")


def _scrub_idea(idea: Dict[str, Any]) -> Dict[str, Any]:
	"""Scrub de la salida cruda del LLM antes de persistirla (MEM-009 S1, MUST-9).

	Solo campos de texto de la idea: los hashes/refs no pasan por el scrub (un
	sha256 podría parecer un token y corromperse).
	"""
	from red_pill.memento.clean import normalize_noise
	from red_pill.memento.scrub import scrub_secrets

	for key in _SCRUB_FIELDS:
		if isinstance(idea.get(key), str):
			idea[key] = scrub_secrets(normalize_noise(idea[key]))
	if isinstance(idea.get("relics"), list):
		idea["relics"] = [scrub_secrets(normalize_noise(str(r))) for r in idea["relics"]]
	return idea


def _contract(voice_rewrite: bool) -> Dict[str, Any]:
	return {"prompt_version": runtime.annotate_prompt_version(), "engine": runtime.engine_id(), "voice_rewrite": bool(voice_rewrite)}


def _empty_partial(contract: Dict[str, Any]) -> Dict[str, Any]:
	return {"contract": contract, "splits": {}, "phases": {ph: "pending" for ph in PHASES}, "annotations": []}


def _load_partial(annotate_dir: Path, contract: Dict[str, Any]) -> Dict[str, Any]:
	"""Parcial compatible con el contrato vigente, o uno vacío (reset con aviso)."""
	empty = _empty_partial(contract)
	path = annotate_dir / _PARTIAL
	if not path.exists():
		return empty
	try:
		data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		logger.warning("annotate: parcial ilegible en %s — se reinicia", annotate_dir)
		return empty
	if data.get("contract") != contract:
		logger.warning("annotate: contrato del parcial distinto (%s ≠ %s) — reset", data.get("contract"), contract)
		return empty
	data.setdefault("splits", {})
	data.setdefault("annotations", [])
	data["phases"] = {ph: (data.get("phases") or {}).get(ph, "pending") for ph in PHASES}
	return data


def _save_partial(annotate_dir: Path, partial: Dict[str, Any]) -> None:
	"""Escritura atómica (tmp+replace). Las ideas ya vienen scrubbeadas de `_extract`."""
	partial["updated_at"] = datetime.now(timezone.utc).isoformat()
	tmp = annotate_dir / (_PARTIAL + ".tmp")
	tmp.write_text(json.dumps(partial, ensure_ascii=False, indent=1), encoding="utf-8")
	tmp.replace(annotate_dir / _PARTIAL)


def _annotations_from_notes(annotate_dir: Path, contract: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
	"""Reconstruye las anotaciones desde las notas materializadas (prerrequisito de `--from`).

	Solo si `_meta.json` casa con el contrato vigente: si no, las notas son de otro
	motor/prompt y no valen como estado previo. None → no hay prerrequisito.
	"""
	meta_path = annotate_dir / "_meta.json"
	if not meta_path.exists():
		return None
	try:
		meta = json.loads(meta_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None
	if meta.get("annotate_prompt_version") != contract["prompt_version"] or meta.get("engine") != contract["engine"]:
		return None
	from red_pill.memento.ascension import parse_refine as _parse_refine

	out: List[Dict[str, Any]] = []
	for note in sorted(annotate_dir.glob("[0-9][0-9][0-9]-*.md")):
		try:
			fm, body = _parse_refine(note.read_text(encoding="utf-8"))
		except Exception:
			continue
		raw_texture = fm.get("texture")
		texture: Dict[str, Any] = raw_texture if isinstance(raw_texture, dict) else {}
		idea: Dict[str, Any] = {
			"title": str(fm.get("title") or "Anotación"),
			"text": str(body or "").strip(),
			"significance": fm.get("significance"),
			"emotion": str(fm.get("emotion") or "gray"),
			"intensity": fm.get("intensity"),
			"theme": str(texture.get("theme") or ""),
			"relics": [str(r) for r in _as_list(texture.get("relics"))][:4],
			"split_ref": str(fm.get("split_ref") or fm.get("source_lines") or ""),
			"nnn": note.name[:3],
		}
		idea["flags"] = quality_flags(idea["text"])
		if fm.get("work_score") is not None and "unscored" not in _as_list(fm.get("quality_flags")):
			idea["work_score"] = float(fm.get("work_score") or 0.0)
			idea["social_score"] = float(fm.get("social_score") or 0.0)
		out.append(idea)
	return out


def _resolve_from(
	from_phase: Optional[str], partial: Dict[str, Any], notes: Optional[List[Dict[str, Any]]], voice_rewrite: bool
) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
	"""`--from`: fase de entrada efectiva + anotaciones previas (degradado gracioso).

	Las fases son secuenciales y mandan los prerrequisitos: la bandera pide
	intención, el estado decide. Sin prerrequisitos → fase factible más temprana,
	avisando. `rewrite` sin voice_rewrite activo se trata como `score`.
	"""
	if from_phase in (None, "extract"):
		return "extract", None
	if from_phase not in PHASES:
		raise ValueError(f"--from inválido: {from_phase!r} (extract|rewrite|score)")
	if from_phase == "rewrite" and not voice_rewrite:
		from_phase = "score"
	prior: Optional[List[Dict[str, Any]]] = None
	if partial["phases"]["extract"] == "done" and partial["annotations"]:
		prior = partial["annotations"]
		if from_phase == "score" and voice_rewrite and partial["phases"]["rewrite"] != "done":
			logger.warning("annotate --from=score: rewrite no completado en el parcial — degrado a rewrite")
			from_phase = "rewrite"
	elif notes:
		prior = notes
	if prior is None:
		logger.warning("annotate --from=%s sin prerrequisitos (ni parcial ni notas del contrato vigente) — degrado a extract", from_phase)
		return "extract", None
	return from_phase, [dict(a) for a in prior]
