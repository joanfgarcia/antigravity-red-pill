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
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import prompts, runtime
from .fragments import _as_list, _frontmatter_block, fragment_view, slugify_title, work_units

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
	r"\bAleth\s+(creó|implementó|propuso|explicó|desplegó|configuró|generó|corrigió|añadió|actualizó|sincronizó|ejecutó|arregló|restauró|omitió)\b",
	re.I,
)
_FIRST_PERSON = re.compile(
	r"\b(me|mi|mis|nos|le|les|he|creé|implementé|propuso|expliqué|dije|hice|desplegué|generé|corregí|configuré|actualicé|sincronicé|ejecuté|arreglé|restauré)\b",
	re.I,
)


_ALETH_OPENER = re.compile(r"^\s*Aleth\s+\w+", re.I)
_EN_WORDS = set("the and of to in is was for with that this from have has had were are by on as it he she they".split())
_ES_WORDS = set("el la los las de que y en un una por para con me le lo se del al es fue su sus como".split())


def looks_english(text: str) -> bool:
	"""¿La nota está en inglés? Recuento de palabras vacías EN vs ES (determinista)."""
	words = re.findall(r"[a-záéíóúüñ]+", text.lower())
	en = sum(w in _EN_WORDS for w in words)
	es = sum(w in _ES_WORDS for w in words)
	return en > es and en >= 3


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


# ── MEM-010 F1: métricas por sesión para el gating (RFC §3.2) ────────────────
# Se computan SIEMPRE sobre las notas FINALES (post rewrite/dedup) y con el
# umbral de dedup efectivo guardado junto a la métrica, para que vivo y
# backfill comparen like-for-like (enmienda r3 del panel).

_BIO_LEAK_PATTERNS = (
	re.compile(r"\bcomo narradora\b", re.I),
	re.compile(r"\bla narradora del b[úu]nker\b", re.I),
	re.compile(r"\bel (?:operador|ingeniero) catal[áa]n\b", re.I),
)


def compute_note_metrics(annotations: List[Dict[str, Any]], *, dedup_threshold: float) -> Dict[str, Any]:
	"""Métricas de calidad de una sesión anotada (deterministas, sin IO)."""
	texts = [str(a.get("text") or "") for a in annotations]
	n = len(texts)
	lens = [len(t) for t in texts]
	toks = [_tokens(t + " " + str(a.get("title") or "")) for t, a in zip(texts, annotations)]
	near_dups = 0
	for i in range(len(toks)):
		for j in range(i + 1, len(toks)):
			a, b = toks[i], toks[j]
			if a and b and len(a & b) / min(len(a), len(b)) > dedup_threshold:
				near_dups += 1
	margins = [
		abs(float(a.get("work_score", 0.0) or 0.0) - float(a.get("social_score", 0.0) or 0.0))
		for a in annotations
		if "work_score" in a and "social_score" in a
	]
	return {
		"notas": n,
		"pct_gt_600": round(100 * sum(1 for x in lens if x > 600) / max(1, n), 1),
		"pct_primera_persona": round(100 * sum(1 for t in texts if is_first_person(t)) / max(1, n), 1),
		"near_dups": near_dups,
		"dedup_threshold": float(dedup_threshold),
		"min_margin": round(min(margins), 3) if margins else None,
		"bio_leaks": sum(1 for t in texts if any(p.search(t) for p in _BIO_LEAK_PATTERNS)),
	}


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
	v2 = runtime.voice_v2_enabled()
	work_scope, social_scope = runtime.annotate_scopes()
	prompt_ids = ("annotate_work_user_v2", "annotate_social_user_v2") if v2 else ("annotate_work_user", "annotate_social_user")
	static = {"identity": prompts.IDENTITY_BIO, "work_scope": work_scope, "social_scope": social_scope}
	for prompt_id in prompt_ids:
		prompt = prompts.render(prompt_id, static=static, fragment=content)
		raw = transport(prompts.system(prompt_id) or "", prompt, 1024)
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
	de RFC-HARNESS-002 §7). Se fija por llamada: el nocturno (stage task=distill)
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
		for unit in units:
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
	meta_tmp = (annotate_dir / "_meta.json").with_suffix(".json.tmp")
	meta_tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
	meta_tmp.replace(annotate_dir / "_meta.json")
	# Solo tras el `_meta` verificado: huérfanos fuera y parcial plegado.
	for stale in annotate_dir.glob("*.md"):
		if stale.name not in written:
			stale.unlink()
	(annotate_dir / _PARTIAL).unlink(missing_ok=True)
	from red_pill.memento.record import update_session_record

	update_session_record(root, dir_rel, "annotate", meta)
	return max_significance
