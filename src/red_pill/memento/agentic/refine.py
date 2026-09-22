"""Refine multi-idea de sesiones Memento: destills → refine/NNN-*.md (RFC-002 §5.4.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import prompts, runtime
from .fragments import _as_list, _frontmatter_block, slugify_title
from .runtime import Transport


def cross_ref_candidates(registry: Any, source: str, session_id: str, limit: int = 12) -> List[str]:
	"""Candidatos mecánicos (§4.5): sesiones de cualquier fuente con solape temporal o mismo workspace."""
	own = registry.get(source, session_id) or {}
	own_day = (own.get("created_at") or "")[:10]
	own_workspace = own.get("workspace")
	candidates = []
	for other_source, sessions in registry.state["registry"].items():
		for other_id, entry in sessions.items():
			if other_id == session_id or not entry.get("dir"):
				continue
			same_day = own_day and (entry.get("created_at") or "")[:10] == own_day
			same_workspace = own_workspace and entry.get("workspace") == own_workspace
			if same_day or same_workspace:
				candidates.append(other_id)
	return sorted(candidates)[:limit]




# ── Fase 4 §5.4.2: refine multi-idea (map-reduce sobre fragments) ──


def _format_fragments(frags: List[Dict[str, Any]], start: int = 1) -> str:
	"""`FRAGMENT i\nTitle: ...\nSummary: ...` para el prompt (índices globales)."""
	return "\n\n".join(f"FRAGMENT {start + i}\nTitle: {s['title']}\nSummary: {s['summary']}" for i, s in enumerate(frags))




def _split_to_fit(frags: List[Dict[str, Any]], candidates: List[str], max_chars: int) -> List[List[Dict[str, Any]]]:
	"""Particiona los fragments en lotes que quepan en `max_chars` (map-reduce
	del refine: no perder ideas por exceso de contexto). Usa el prompt de refine
	más largo (WORK) como referencia de tamaño."""
	lots = [frags]
	while True:
		next_lots: List[List[Dict[str, Any]]] = []
		split = False
		for lot in lots:
			prompt_len = len(prompts.REFINE_WORK_USER.format(voice=prompts._VOICE_RULE, candidates=json.dumps(candidates), fragments=_format_fragments(lot)))
			if prompt_len <= max_chars or len(lot) <= 1:
				next_lots.append(lot)
			else:
				mid = len(lot) // 2
				next_lots.append(lot[:mid])
				next_lots.append(lot[mid:])
				split = True
		lots = next_lots
		if not split:
			return lots




def _refine_multi(transport: Transport, frags: List[Dict[str, Any]], candidates: List[str]) -> List[Dict[str, Any]]:
	"""Extrae ideas (array JSON) de M fragments, particionando en lotes si el
	prompt excede el presupuesto. → lista de ideas con `fragment_ref` global.

	Hace DOS llamadas por lote (2026-09-15, bake-off): una WORK y una SOCIAL.
	Los modelos locales se confunden si un solo prompt pide ambos tipos a la vez
	(devuelven [] en contenido mixto); cada llamada enfocada captura su tipo."""
	ideas: List[Dict[str, Any]] = []
	cursor = 0
	for lot in _split_to_fit(frags, candidates, runtime.model_prompt_budget()):
		fragments = _format_fragments(lot, cursor)
		cands = json.dumps(candidates)
		for system, template in ((prompts.REFINE_WORK_SYSTEM, prompts.REFINE_WORK_USER), (prompts.REFINE_SOCIAL_SYSTEM, prompts.REFINE_SOCIAL_USER)):
			prompt = template.format(voice=prompts._VOICE_RULE, candidates=cands, fragments=fragments)
			raw = transport(system, prompt, 1024)
			ideas.extend(runtime._extract_json_array(raw) or [])
		cursor += len(lot)
	return ideas




def _dedup_ideas(ideas: List[Dict[str, Any]], threshold: float = 0.6) -> List[Dict[str, Any]]:
	"""Deduplica ideas del MISMO work unit (2026-09-15).

	Las dos llamadas (WORK y SOCIAL) sobre el mismo fragmento producen a veces la
	MISMA idea con clasificaciones distintas (contenido mixto: la técnica en WORK
	cat~0.9 y su "versión social" en SOCIAL cat~0.3). Se conserva UNA: la de mayor
	significance; en empate, la de `category_score` más extremo (más lejos del
	limbo 0.5 → clasificación más clara)."""
	import re

	def toks(idea: Dict[str, Any]) -> set:
		text = " ".join([str(idea.get("title", "")), str(idea.get("theme", "")), " ".join(str(r) for r in _as_list(idea.get("relics")))])
		return set(re.findall(r"[a-záéíóúüñ]{4,}", text.lower()))

	def rank(idea: Dict[str, Any]):
		try:
			sig = float(idea.get("significance", 0) or 0)
		except (TypeError, ValueError):
			sig = 0.0
		try:
			cat = float(idea.get("category_score", 0.5) or 0.5)
		except (TypeError, ValueError):
			cat = 0.5
		return (sig, abs(cat - 0.5))

	kept: List[Dict[str, Any]] = []
	kept_tokens: List[set] = []
	for idea in sorted(ideas, key=rank, reverse=True):
		t = toks(idea)
		if any(t and kt and len(t & kt) / min(len(t), len(kt)) > threshold for kt in kept_tokens):
			continue
		kept.append(idea)
		kept_tokens.append(t)
	return kept




def refine_session(
	root: Path,
	dir_rel: str,
	session_id: str,
	source: str,
	sections: List[Dict[str, Any]],
	candidates: List[str],
	transport: Transport,
	min_significance: float,
) -> float:
	"""Escribe refine/NNN-<slug>.md por IDEA extraída del work unit (Fase 4 §5.4.2).

	Agrupa los destills de cada work unit (NNN; los fragmentos comparten nnn) y
	`_refine_multi` extrae N ideas (0..N). Cada idea que supera `min_significance`
	escribe UN refine. El 1:1 anterior (1 distill → 1 refine) queda obsoleto."""
	refine_dir = root / dir_rel / "refine"
	refine_dir.mkdir(parents=True, exist_ok=True)
	# Preservar el sello de ascensión de los refines previos con la MISMA identidad
	# (`source_lines`): la re-destilización no debe des-ascender lo que ya está
	# promocionado — `ascender` es un upsert idempotente por esa clave.
	prev_seals: Dict[str, Dict[str, Any]] = {}
	for prev in refine_dir.glob("*.md"):
		try:
			from red_pill.memento.ascension import parse_refine as _parse_refine

			pfm, _ = _parse_refine(prev.read_text(encoding="utf-8"))
		except Exception:
			continue
		if pfm.get("ascended"):
			prev_seals[str(pfm.get("source_lines") or "")] = {
				"ascended": True,
				"ascended_at": pfm.get("ascended_at"),
				"ascended_to": pfm.get("ascended_to"),
				"ascended_point_id": pfm.get("ascended_point_id"),
				"polaroid_stability": pfm.get("polaroid_stability") or 0.0,
				"last_reinforced_at": pfm.get("last_reinforced_at"),
			}
	for stale in refine_dir.glob("*.md"):
		stale.unlink()

	groups: Dict[str, List[Dict[str, Any]]] = {}
	for s in sections:
		groups.setdefault(s["nnn"], []).append(s)

	max_significance = 0.0
	for nnn, frags in sorted(groups.items()):
		for idea in _dedup_ideas(_refine_multi(transport, frags, candidates)):
			try:
				significance = max(0.0, min(1.0, float(idea.get("significance", 0.0))))
			except (TypeError, ValueError):
				significance = 0.0
			max_significance = max(max_significance, significance)
			if significance < min_significance:
				continue
			title = str(idea.get("title") or f"Idea {nnn}")[:80]
			slug = slugify_title(title)
			try:
				ref_idx = int(idea.get("fragment_ref") or 1)
			except (TypeError, ValueError):
				ref_idx = 1
			origin = frags[ref_idx - 1] if 1 <= ref_idx <= len(frags) else frags[0]
			cross_refs = [c for c in _as_list(idea.get("cross_refs")) if c in candidates]
			try:
				category_score = max(0.0, min(1.0, float(idea.get("category_score", 0.5) or 0.5)))
			except (TypeError, ValueError):
				category_score = 0.5
			# Sanear relicas: el LLM a veces devuelve un int en vez de un array.
			relics = [str(r) for r in _as_list(idea.get("relics"))][:4]
			seal = prev_seals.get(str(origin["source_lines"]), {})
			refine_fm = _frontmatter_block(
				[
					("session_id", session_id),
					("source", source),
					("distill_ref", f"distill/{origin['file']}"),
					("source_lines", origin["source_lines"]),
					("significance", significance),
					("emotion", str(idea.get("emotion", "gray"))),
					("intensity", float(idea.get("intensity", 0.0) or 0.0)),
					("texture", {"theme": str(idea.get("theme", "")), "relics": relics}),
					("cross_refs", cross_refs),
					("fragment_ref", ref_idx if len(frags) > 1 else None),
					("category_score", category_score),
					("engine", runtime.engine_id()),
					("prompt_version", runtime.refine_prompt_version()),
					# Estado de ascensión (Fase 4 §3): se preserva si la identidad (source_lines) no cambió.
					("ascended", bool(seal.get("ascended", False))),
					("ascended_at", seal.get("ascended_at")),
					("ascended_to", seal.get("ascended_to")),
					("ascended_point_id", seal.get("ascended_point_id")),
					("polaroid_stability", seal.get("polaroid_stability", 0.0)),
					("last_reinforced_at", seal.get("last_reinforced_at")),
				]
			)
			(refine_dir / f"{nnn}-{slug}.md").write_text(f"{refine_fm}\n\n{origin['summary']}\n", encoding="utf-8")
	return max_significance
