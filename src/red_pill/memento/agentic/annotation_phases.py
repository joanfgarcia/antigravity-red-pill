"""Annotate phase logic — extract, voice rewrite, post-rewrite dedup and dual scoring.

Split from annotate.py (SHARD-PS-04). Consumes the transport; no partial-state IO.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import prompts, runtime
from .annotation_quality import _ALETH_OPENER, dedup_annotations, is_first_person, looks_english, quality_flags
from .fragments import _as_list

logger = logging.getLogger(__name__)


_SCORE_BATCH = 20


def _extract(transport: runtime.Transport, content: str) -> List[Dict[str, Any]]:
	ideas: List[Dict[str, Any]] = []
	# 2026-10-30: la variante la dicta el modelo juez (perfil → annotate_prompt_set).
	# v3 = mismo contrato de voz que v2, pero pide el ACTO y no la escena.
	setc = runtime.annotate_prompt_set()
	work_scope, social_scope = runtime.annotate_scopes()
	prompt_ids = {
		"v3": ("annotate_work_user_v3", "annotate_social_user_v3"),
		"v2": ("annotate_work_user_v2", "annotate_social_user_v2"),
	}.get(setc, ("annotate_work_user", "annotate_social_user"))
	static = {"identity": prompts.IDENTITY_BIO, "work_scope": work_scope, "social_scope": social_scope}
	for prompt_id in prompt_ids:
		prompt = prompts.render(prompt_id, static=static, fragment=content)
		raw = transport(prompts.system(prompt_id) or "", prompt, runtime.annotate_max_tokens())
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


def _needs_voice_rewrite(text: str) -> bool:
	"""¿La nota necesita re-escritura de voz? Solo si tiene la bandera `voice`.

	2026-09-25: antes el criterio era "no está en 1ª persona", y el prompt exigía
	empezar por "Joan me…" y prohibía "Joan implementó". Resultado medido: el 50,2%
	de las notas abría con la muletilla y había inversiones de sujeto ("Joan me
	comprometió dos cambios" por commits de Aleth). Una nota que narra una acción de
	Joan con Joan como sujeto ya es correcta; se reescriben solo las impersonales o
	en 3ª persona de Aleth (`quality_flags` → `voice`).
	"""
	if not runtime.voice_v2_enabled():
		return not is_first_person(text)  # voz v1
	# v2.1 (piloto 2026-09-26): el detector `voice` solo conoce patrones en español;
	# las notas que el modelo escribió en inglés y en 3ª persona ("Aleth updated…")
	# pasaban sin reescribir. También se reescriben si están en inglés o si abren
	# con "Aleth <verbo>" (el narrador hablando de sí mismo en 3ª persona).
	return "voice" in quality_flags(text) or looks_english(text) or bool(_ALETH_OPENER.match(text))


def rewrite_voice_notes(transport: runtime.Transport, annotations: List[Dict[str, Any]], batch_size: int = 10) -> int:
	"""Re-escribe la voz de las notas con bandera `voice` (MEM-006 Q8, lever b).

	Reintenta con lotes decrecientes hasta individual (el modelo responde a veces
	solo una parte). Actualiza `text` y recalcula `flags` in-place. Devuelve cuántas
	se reescribieron.
	"""
	rewritten = 0
	for size in (batch_size, 4, 1):
		pending = [a for a in annotations if _needs_voice_rewrite(str(a.get("text") or ""))]
		if not pending:
			break
		for start in range(0, len(pending), size):
			chunk = pending[start : start + size]
			listing = "\n\n".join(f"[{i}] {a['text'][:600]}" for i, a in enumerate(chunk))
			prompt_id = "voice_rewrite_user_v2" if runtime.voice_v2_enabled() else "voice_rewrite_user"
			user = prompts.render(prompt_id, static={"identity": prompts.IDENTITY_BIO}, notes=listing)
			raw = transport(prompts.system(prompt_id) or "", user, 2048)
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


def dedup_post_rewrite(
	annotations: List[Dict[str, Any]],
	threshold: float = 0.90,
	embed_fn: Optional[Any] = None,
) -> List[Dict[str, Any]]:
	"""Dedup DESPUÉS de la re-escritura de voz (feedback de recall 2026-09-25).

	La dedup P1-A corre sobre las ideas crudas; la re-escritura puede hacer que dos
	ideas distintas acaben con el mismo texto (7 duplicados exactos en el corpus) o
	con paráfrasis casi idénticas. Dos pasadas: (1) P1-A otra vez (hash normalizado
	+ solape de tokens); (2) casi-duplicados por embedding dentro de la sesión:
	coseno ≥ `threshold` entre cuerpos sin muletilla → se queda la mejor variante
	(mismo orden de `_rank`). Umbral 0,90 medido: en el corpus, los pares de la
	misma sesión en 0,90-0,93 son el mismo hecho dicho dos veces.

	`embed_fn(textos) -> vectores` inyectable (tests); por defecto, el embedder vigente.
	"""
	kept = dedup_annotations(annotations)
	if threshold <= 0 or len(kept) < 2:
		return kept
	from red_pill.memento.embed_text import strip_lead

	texts = [strip_lead(str(a.get("text") or "")) or str(a.get("text") or "") for a in kept]
	if embed_fn is None:
		from red_pill.core.embeddings import EmbeddingEngine

		engine = EmbeddingEngine()
		engine.get_vector("warmup")
		encoder: Any = engine.encoder
		vectors = list(encoder.embed(texts, batch_size=64))
	else:
		vectors = list(embed_fn(texts))
	import numpy as np

	units = []
	for v in vectors:
		arr = np.asarray(v, dtype=float)
		n = float(np.linalg.norm(arr))
		units.append(arr / n if n else arr)
	out: List[Dict[str, Any]] = []
	out_units: List[Any] = []
	for a, u in zip(kept, units):  # `kept` ya viene ordenado por `_rank` (mejor primero)
		if any(float(u @ w) >= threshold for w in out_units):
			continue
		out.append(a)
		out_units.append(u)
	return out


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
			if runtime.voice_v2_enabled():
				work_scope, social_scope = runtime.annotate_scopes()
				prompt_id = "dual_score_user_v2"
				user = prompts.render(prompt_id, static={"work_scope": work_scope, "social_scope": social_scope}, memories=listing)
			else:
				prompt_id = "dual_score_user"
				user = prompts.render(prompt_id, memories=listing)
			raw = transport(prompts.system(prompt_id) or "", user, 2048)
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


def _with_annotate_task(transport: runtime.Transport) -> runtime.Transport:
	"""Envuelve el transporte fijando `RP_LLM_TASK=annotate` durante cada llamada.

	Annotate tiene su PROPIO contrato task (el carril refine/distill era un apaño
	de AD-030). Se fija por llamada: el nocturno (stage task=distill)
	y el rebuild (task=annotate) usan el mismo contrato sin cambiar sus recipes.
	"""

	def call(system: str, user: str, max_tokens: int) -> str:
		previous = os.environ.get("RP_LLM_TASK")
		os.environ["RP_LLM_TASK"] = "annotate"
		try:
			return transport(system, user, max_tokens)
		finally:
			if previous is None:
				os.environ.pop("RP_LLM_TASK", None)
			else:
				os.environ["RP_LLM_TASK"] = previous

	return call
