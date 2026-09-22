"""Ascensión curada Memento → Qdrant (RFC-002 Fase 4, §3).

Memento es el archivo; la memoria curada vive en `work_memories`/`social_memories`.
`ascender()` promociona un `refine/*.md` a engrama curado. Es **idempotente**:
el point id se deriva de `(session_id, source_lines)`, así que re-promover el
mismo refine es un upsert, nunca un duplicado. El sello (`ascended: true`) vive
en el frontmatter del refine — Memento sigue siendo la fuente de verdad.

El gate de curaduría (§4.6) decide *qué* asciende; este módulo solo ejecuta la
promoción. El ascenso por refuerzo (`weave_memento_reinforcement`) y el estático
(umbral de significance) se apoyan en esta misma función.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml
from qdrant_client import models

from red_pill.memento.render import update_frontmatter_fields  # noqa: F401 (re-export API)

logger = logging.getLogger(__name__)

# Claves del frontmatter del refine que sellan el estado de ascensión.
# Se declaran en `refine_session` con defaults para poder actualizarlas in-place
# (sin mover el cuerpo del refine — §4.5.1).
ASCENSION_FIELDS = ("ascended", "ascended_at", "ascended_to", "ascended_point_id")

# Estabilidad de refuerzo (RFC-002 Fase 4 §3.2). Ajustados por el experimento de
# calibración 2026-09-14 (§6.9): GAIN=1.0/gate=5.0 saturaban el corpus real;
# GAIN=0.5+gate=7.0 asciende una minoría sostenida.
POLAROID_TAU_DEFAULT = 90.0  # días: un tema silenciado ~3 meses pierde la mayor parte de la estabilidad
POLAROID_GAIN_DEFAULT = 0.5  # incremento por reaparición
POLAROID_REVIVAL_GATE_DEFAULT = 7.0  # umbral de ascenso por refuerzo


def _polaroid_cfg(default: float, key: str) -> float:
	try:
		import red_pill.config as cfg

		return float(getattr(cfg, key, default))
	except Exception:
		return default


def polaroid_decay(stability: float, last_reinforced_at: Any, now: float, tau: float) -> float:
	"""Decaimiento exponencial entre refuerzos: S *= e^(-Δt/τ) (modelo half-life).

	`last_reinforced_at` puede ser None (sin historia → sin decay), epoch float,
	o ISO string (timezone-aware). `tau` en días, `now` en segundos."""
	if stability <= 0 or not last_reinforced_at:
		return stability
	from datetime import date as _date

	from red_pill.memento.render import _to_datetime

	if isinstance(last_reinforced_at, datetime):
		last_dt = last_reinforced_at
	elif isinstance(last_reinforced_at, _date):
		last_dt = datetime(last_reinforced_at.year, last_reinforced_at.month, last_reinforced_at.day, tzinfo=timezone.utc)
	else:
		last_dt = _to_datetime(last_reinforced_at) or datetime.now(tz=timezone.utc)
	if last_dt is None:
		return stability
	dt_days = max(0.0, (now - last_dt.timestamp()) / 86400.0)
	return stability * math.exp(-dt_days / max(tau, 0.1))


def reinforce_refine(
	root: Path,
	registry: Any,
	refine_path: Path,
	*,
	now: Optional[float] = None,
	tau: Optional[float] = None,
	gain: Optional[float] = None,
	gate: Optional[float] = None,
	memory_manager: Any = None,
	transport: Any = None,
) -> Dict[str, Any]:
	"""Aplica un refuerzo a un refine NO ascendido: decay temporal + GAIN, y si la
	estabilidad resultante supera el gate de resurrección, lo asciende (Fase 4 §3.2).

	- `tau`/`gain`/gate: del config (POLAROID_TAU/GAIN/REVIVAL_GATE) con defaults
	provisionales si no están declarados.
	- Escribe `polaroid_stability` y `last_reinforced_at` en el frontmatter
	(in-place, atómico) y los espeja en el registry.
	- Los refinados ya ascendidos no se refuerzan (dejan de competir).
	"""
	if now is None:
		now = time.time()
	tau = _polaroid_cfg(POLAROID_TAU_DEFAULT, "POLAROID_TAU") if tau is None else tau
	gain = _polaroid_cfg(POLAROID_GAIN_DEFAULT, "POLAROID_GAIN") if gain is None else gain
	gate = _polaroid_cfg(POLAROID_REVIVAL_GATE_DEFAULT, "POLAROID_REVIVAL_GATE") if gate is None else gate

	refine_path = Path(refine_path)
	fm, body = parse_refine(refine_path.read_text(encoding="utf-8"))
	if not body:
		return {"reinforced": False, "reason": "empty_body"}
	if fm.get("ascended"):
		return {"reinforced": False, "reason": "already_ascended", "stability": float(fm.get("polaroid_stability", 0.0) or 0.0)}

	source = str(fm.get("source") or "")
	session_id = str(fm.get("session_id") or "")

	stability = float(fm.get("polaroid_stability", 0.0) or 0.0)
	last_reinforced = fm.get("last_reinforced_at")
	decayed = polaroid_decay(stability, last_reinforced, now, tau)
	new_stability = decayed + gain
	last_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

	_stamp_refine(
		refine_path,
		{"polaroid_stability": round(new_stability, 2), "last_reinforced_at": last_iso},
	)
	if source and session_id:
		registry.upsert(source, session_id, {"polaroid_stability": round(new_stability, 2), "last_reinforced_at": last_iso})

	if new_stability >= gate:
		logger.info(f"[POLAROID] {refine_path.name} estabilidad {new_stability:.2f} ≥ gate {gate} — asciende por refuerzo")
		ascended = ascender(root, registry, refine_path, memory_manager=memory_manager, transport=transport)
		return {"reinforced": True, "stability": round(new_stability, 2), "gate": gate, "ascended": ascended.get("ascended", False)}

	return {"reinforced": True, "stability": round(new_stability, 2), "gate": gate, "ascended": False}


# ── Fase 4 §4.2: el paso Memento-consciente del weaver ──

_STOPWORDS = {
	"para",
	"esta",
	"este",
	"esto",
	"como",
	"más",
	"una",
	"uno",
	"cada",
	"sido",
	"tiene",
	"tener",
	"hacer",
	"puede",
	"entre",
	"sobre",
	"desde",
	"todos",
	"todo",
	"parte",
	"nuestro",
	"nuestra",
	"quiere",
	"sistema",
	"siendo",
	"estado",
	"también",
	"sesión",
	"sesion",
	"fase",
	"fase",
	"nuevo",
	"nueva",
	"mismo",
	"misma",
	"forma",
	"when",
	"that",
	"with",
	"from",
	"this",
	"have",
	"been",
	"into",
	"the",
	"and",
	"were",
	"will",
	"would",
	"should",
	"could",
	"about",
	"after",
	"before",
	"their",
}


def _topic_tokens(text: Any) -> set:
	"""Tokens normalizados de un texto/tema: minúsculas, ≥4 chars, sin stopwords."""
	if text is None:
		return set()
	out = set()
	for word in str(text).lower().replace("_", " ").replace("-", " ").split():
		word = "".join(ch for ch in word if ch.isalnum())
		if len(word) >= 4 and word not in _STOPWORDS:
			out.add(word)
	return out


def _engram_topics(payload: Dict[str, Any]) -> set:
	"""Temas de un engrama: theme, texture (hub), keywords y relics normalizados."""
	topics: set = set()
	texture = payload.get("texture")
	if isinstance(texture, dict):
		theme = texture.get("theme")
		if theme:
			topics.add(str(theme))
		for relic in texture.get("relics", []) or []:
			topics.update(_topic_tokens(relic))
	else:
		topics.update(_topic_tokens(texture))
	for key in ("theme", "keywords", "relics"):
		val = payload.get(key)
		if isinstance(val, str):
			topics.update(_topic_tokens(val))
		elif isinstance(val, list):
			for item in val:
				topics.update(_topic_tokens(item))
	topics.update(_topic_tokens(payload.get("summary") or payload.get("content")))
	return topics


def _refine_topics(fm: Dict[str, Any], body: str):
	"""Temas de un refine: el theme exacto (snake_case) es el ancla fuerte;
	los relics y el cuerpo aportan tokens. → (tema_exacto: str, tokens: set)."""
	texture = fm.get("texture") if isinstance(fm.get("texture"), dict) else {}
	theme = str(texture.get("theme", "") or "") if texture else ""
	tokens: set = set()
	for relic in texture.get("relics") or [] if texture else []:
		tokens.update(_topic_tokens(relic))
	tokens.update(_topic_tokens(body))
	return theme, tokens


def _temas_afines(refine_theme: str, refine_tokens: set, engrama_topics: set) -> bool:
	"""Fase 4 §3.2: matching exacto de theme (snake_case) o cruce de ≥3 tokens.

	≥2 tokens resultó demasiado amplio en el corpus real (calibración 2026-09-14):
	con ~12K engramas recientes casi todo refine matcheaba → el gate saturaba.
	El theme exacto es la señal fuerte; el cruce de tokens exige especificidad."""
	if refine_theme and refine_theme in engrama_topics:
		return True
	return len(refine_tokens & engrama_topics) >= 3


def weave_memento_reinforcement(
	memory_manager: Any = None,
	root: Optional[Path] = None,
	registry: Any = None,
	*,
	now: Optional[float] = None,
	window_hours: Optional[float] = None,
	tau: Optional[float] = None,
	gain: Optional[float] = None,
	gate: Optional[float] = None,
	transport: Any = None,
) -> Dict[str, Any]:
	"""Paso Memento-consciente del weaver (Fase 4 §4.2).

	1. Colecciona los temas de los engramas nuevos en `work_memories` (ventana
	temporal, `AXON_WINDOW_HOURS`).
	2. Para cada `refine/*.md` NO ascendido del árbol Memento, si hay afinidad de
	tema (`_temas_afines`) → `reinforce_refine` (decay + GAIN).
	3. Si la estabilidad supera `POLAROID_REVIVAL_GATE` → `ascender()`.

	No toca `weave_cross_axons`: los axones Qdrant↔Qdrant son cosa de `axons.py`;
	aquí Memento es la fuente de candidatos a promoción, no un nodo.
	"""
	if memory_manager is None:
		from red_pill.memory import MemoryManager

		memory_manager = MemoryManager()
	if root is None:
		from red_pill.memento import get_memento_root

		root = get_memento_root()
	if registry is None:
		from red_pill.memento.registry import MementoRegistry

		registry = MementoRegistry()
	if now is None:
		now = time.time()
	if window_hours is None:
		window_hours = _polaroid_cfg(24.0, "AXON_WINDOW_HOURS")

	client = memory_manager.client
	stats = {"engramas_en_ventana": 0, "refine_evaluados": 0, "refuerzos_aplicados": 0, "ascensos": 0, "errores": 0}

	window_start = now - window_hours * 3600.0

	# 1. Temas de los engramas nuevos en la ventana curada (work + social).
	engrama_topics: set = set()
	for collection in ("work_memories", "social_memories"):
		if not client.collection_exists(collection):
			continue
		offset = None
		while True:
			batch, offset = client.scroll(
				collection_name=collection,
				scroll_filter=models.Filter(
					must=[models.FieldCondition(key="created_at", range=models.Range(gte=window_start))],
					must_not=[models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent"))],
				),
				limit=64,
				with_payload=True,
				with_vectors=False,
				offset=offset,
			)
			for point in batch:
				engrama_topics.update(_engram_topics(point.payload or {}))
			stats["engramas_en_ventana"] += len(batch)
			if offset is None:
				break

	if not engrama_topics:
		logger.info("[MEM-REINFORCE] Sin engramas nuevos en la ventana — no hay temas que reforzar.")
		return stats

	# 2. Refuerzo de refinados/anotaciones no ascendidos con temas afines.
	paths = sorted(set(Path(root).rglob("refine/*.md")) | set(Path(root).rglob("annotate/*.md")))
	per_session_asc: Dict[str, int] = {}
	for refine_path in paths:
		try:
			fm, body = parse_refine(refine_path.read_text(encoding="utf-8"))
			if not body or fm.get("ascended"):
				continue
			stats["refine_evaluados"] += 1
			refine_theme, refine_tokens = _refine_topics(fm, body)
			if not _temas_afines(refine_theme, refine_tokens, engrama_topics):
				continue
			result = reinforce_refine(
				root, registry, refine_path, now=now, tau=tau, gain=gain, gate=gate, memory_manager=memory_manager, transport=transport
			)
			if result.get("reinforced"):
				stats["refuerzos_aplicados"] += 1
				if result.get("ascended"):
					stats["ascensos"] += 1
					rel = refine_path.relative_to(root).parts
					if len(rel) >= 3:
						dir_rel = str(Path(*rel[:3]))
						per_session_asc[dir_rel] = per_session_asc.get(dir_rel, 0) + 1
		except Exception as e:
			stats["errores"] += 1
			logger.warning(f"[MEM-REINFORCE] fallo en {refine_path}: {e}")

	if per_session_asc:
		from red_pill.memento.record import bump_session_record

		for dir_rel, count in per_session_asc.items():
			bump_session_record(root, dir_rel, "ascend", {"ascendidos": count, "por_refuerzo": count})

	if stats["refuerzos_aplicados"]:
		registry.save()
	logger.info(f"[MEM-REINFORCE] {stats}")
	return stats


# ── Fase 4 §3.3: ascenso estático (gate de significance) ──


def _pick_ascension_winner(entries: list) -> Any:
	"""Ganador determinista de un grupo duplicado (mismo `session_id`+`source_lines`).

	Criterio: mayor `significance`, luego `category_score`, luego cuerpo más largo;
	desempate final por hash del cuerpo (estable entre ejecuciones, así reelegir
	con los mismos datos da el mismo ganador → idempotente).
	"""
	import hashlib

	def _key(c: Any) -> Any:
		_refine_path, fm, body, significance = c
		cat = float(fm.get("category_score", 0.0) or 0.0)
		return (significance, cat, len(body), hashlib.sha256(body.encode("utf-8")).hexdigest())

	return max(entries, key=_key)


def ascend_by_threshold(
	root: Path,
	registry: Any,
	*,
	min_significance: Optional[float] = None,
	memory_manager: Any = None,
	limit: Optional[int] = None,
	transport: Any = None,
	dry_run: bool = False,
) -> Dict[str, Any]:
	"""Ascenso estático (§3.3): promueve los `refine/*.md` y `annotate/*.md` NO
	ascendidos cuya `significance` supera el umbral de su categoría —
	`MEMENTO_GATE_MIN_SIGNIFICANCE_WORK` o `_SOCIAL` (D24: work y social se
	comportan distinto). Un `min_significance` explícito (reseeds/tests) gana para
	todos. Las anotaciones con `dual_route: none` no ascienden (MEM-006).
	`dry_run` informa (`would_ascend`) sin escribir. Idempotente (`ascender` es un
	upsert por `session_id`+`source_lines`+slug).
	"""
	if memory_manager is None:
		from red_pill.memory import MemoryManager

		memory_manager = MemoryManager()

	stats = {"refine_evaluados": 0, "ascendidos": 0, "rechazados_por_umbral": 0, "rechazados_por_ruta": 0, "errores": 0, "duplicados_omitidos": 0}

	candidates = []
	paths = sorted(set(Path(root).rglob("refine/*.md")) | set(Path(root).rglob("annotate/*.md")))
	for refine_path in paths:
		try:
			fm, body = parse_refine(refine_path.read_text(encoding="utf-8"))
			if not body or fm.get("ascended"):
				continue
			stats["refine_evaluados"] += 1
			# MEM-006: las anotaciones sin ruta (ruido/zona muerta) NO ascienden.
			if str(fm.get("dual_route") or "").strip().lower() == "none":
				stats["rechazados_por_ruta"] += 1
				continue
			significance = float(fm.get("significance", 0.0) or 0.0)
			if min_significance is not None:
				threshold = float(min_significance)
			else:
				cat = _candidate_category(fm, body)
				if cat == "work":
					threshold = _polaroid_cfg(0.6, "MEMENTO_GATE_MIN_SIGNIFICANCE_WORK")
				else:
					threshold = _polaroid_cfg(0.5, "MEMENTO_GATE_MIN_SIGNIFICANCE_SOCIAL")
			if significance < threshold:
				stats["rechazados_por_umbral"] += 1
				continue
			candidates.append((refine_path, fm, body, significance))
		except Exception as e:
			stats["errores"] += 1
			logger.warning(f"[STATIC-ASCENSION] fallo en {refine_path}: {e}")

	# Dedup-at-ascension (SW_DEDUP_ENABLED, D12): un grupo duplicado
	# (session_id, source_lines) produce varios refines con el mismo cuerpo y
	# títulos distintos. Se asciende UN ganador determinista; los perdedores NO
	# se borran (la selección puede variar con los parámetros).
	import red_pill.config as _cfg

	if bool(getattr(_cfg, "SW_DEDUP_ENABLED", False)):
		import hashlib

		groups: Dict[Any, list] = {}
		for c in candidates:
			# La clave incluye el HASH DEL CUERPO: un mismo `source_lines` produce
			# VARIAS ideas (multi-idea); agrupar solo por (session_id, source_lines)
			# colapsaría ideas legítimamente distintas. Duplicado real = mismo cuerpo.
			body_hash = hashlib.sha256(str(c[2]).encode("utf-8")).hexdigest()
			key = (str(c[1].get("session_id") or ""), str(c[1].get("source_lines") or ""), body_hash)
			groups.setdefault(key, []).append(c)
		winners = []
		for entries in groups.values():
			winners.append(_pick_ascension_winner(entries))
			stats["duplicados_omitidos"] += len(entries) - 1
		candidates = winners

	if dry_run:
		stats["would_ascend"] = len(candidates)
		stats["ascendidos"] = 0
		logger.info(f"[STATIC-ASCENSION][dry-run] {stats}")
		return stats

	per_session: Dict[str, int] = {}
	for refine_path, fm, body, significance in candidates:
		if limit is not None and stats["ascendidos"] >= limit:
			break
		try:
			result = ascender(root, registry, refine_path, memory_manager=memory_manager, transport=transport)
			if result.get("ascended"):
				stats["ascendidos"] += 1
				rel = refine_path.relative_to(root).parts
				if len(rel) >= 3:
					dir_rel = str(Path(*rel[:3]))
					per_session[dir_rel] = per_session.get(dir_rel, 0) + 1
		except Exception as e:
			stats["errores"] += 1
			logger.warning(f"[STATIC-ASCENSION] fallo en {refine_path}: {e}")

	if per_session:
		from red_pill.memento.record import bump_session_record

		for dir_rel, count in per_session.items():
			bump_session_record(root, dir_rel, "ascend", {"ascendidos": count})
	if stats["ascendidos"]:
		registry.save()
	logger.info(f"[STATIC-ASCENSION] {stats}")
	return stats


def parse_refine(text: str) -> Tuple[Dict[str, Any], str]:
	"""`refine/*.md` → (frontmatter dict, cuerpo). El frontmatter se serializa como
	YAML/JSON (flow), así que `yaml.safe_load` lo lee; el cuerpo va tras el cierre."""
	lines = text.split("\n")
	if not lines or lines[0].strip() != "---":
		return {}, text.strip()
	close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
	if close is None:
		return {}, text.strip()
	try:
		fm = yaml.safe_load("\n".join(lines[1:close])) or {}
	except Exception:
		fm = {}
	if not isinstance(fm, dict):
		fm = {}
	return fm, "\n".join(lines[close + 1 :]).strip()


def refine_point_id(session_id: str, source_lines: str, discriminator: str = "") -> str:
	"""Point id determinista (uuid5) → idempotencia por refine.

	Incluye un `discriminator` (el slug del refine) porque un MISMO work unit
	(`source_lines`) produce VARIAS ideas (multi-idea): sin él, dos ideas del
	mismo fragmento colisionaban en el mismo id y el segundo upsert sobreescribía
	al primero (fix 2026-09-15). Re-promover el MISMO refine reutiliza el id
	(upsert, no duplica)."""
	key = f"memento:{session_id}:{source_lines}:{discriminator}"
	return str(uuid.uuid5(uuid.NAMESPACE_OID, key))


def _relative_refine_ref(root: Path, refine_path: Path) -> str:
	try:
		return str(refine_path.relative_to(root))
	except ValueError:
		return refine_path.name


def _stamp_refine(refine_path: Path, fields: Dict[str, Any]) -> None:
	"""Sella campos en el frontmatter de un refine: reemplaza in-place si la clave
	existe, o la añade antes del cierre si falta. Seguro para el refine (no tiene
	line refs ni `memento_hash` como `memento/index.md`), y necesario porque los
	refine escritos por versiones anteriores no declaran las claves de ascensión."""
	from red_pill.memento.render import _yaml_value

	text = refine_path.read_text(encoding="utf-8")
	lines = text.split("\n")
	if not lines or lines[0].strip() != "---":
		return
	close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
	if close is None:
		return
	line_of: Dict[str, int] = {}
	for i in range(1, close):
		if ":" in lines[i]:
			line_of[lines[i].split(":", 1)[0].strip()] = i
	additions = []
	for key, value in fields.items():
		rendered = f"{key}: {_yaml_value(value)}"
		if key in line_of:
			lines[line_of[key]] = rendered
		else:
			additions.append(rendered)
	if additions:
		lines = lines[:close] + additions + lines[close:]
	refine_path.write_text("\n".join(lines), encoding="utf-8")


def _curated_importance(significance: float) -> float:
	"""Importance de un engrama ascendido: significance × factor configurable.

	El motor bayesiano usa α = max(1, importance): con α alta la utility inicial
	es alta y el engrama tarda años en erodar (vs ~19 días de uno normal). Así lo
	curado desde Memento no se olvida (decisión Fase 4, 2026-09-14)."""
	try:
		import red_pill.config as cfg

		factor = float(getattr(cfg, "MEMENTO_CURATED_IMPORTANCE_FACTOR", 5.0))
	except Exception:
		factor = 5.0
	return max(1.0, round(significance * factor, 2))


CLASSIFY_SYSTEM = "You are the Bünker Curator. You score how 'work' vs 'social' a memory is. Output ONLY valid JSON."
CLASSIFY_USER = """Score how much this distilled memory is "work" (technical/operational) vs "social" (personal/reflective/philosophical).

- 1.0 = purely work (code, systems, architecture, infrastructure).
- 0.0 = purely social/personal/reflective.
- Ambiguity sits in the middle.

Memory:
{body}

Output ONLY the JSON object: {{"category_score": 0.0}}
"""


def _classify_llm(transport: Any, body: str) -> Optional[float]:
	"""Clasifica work/social como RATIO (0-1, 1 = work) con el LLM — el curador
	entiende el contexto, a diferencia de la heurística por tokens (receta del
	desastre 2026-09-14: los resúmenes técnicos perdían la densidad del código y
	caían a social). None si el LLM no responde un score claro."""
	if transport is None:
		return None
	from red_pill.memento.agentic import _extract_json

	try:
		raw = transport(CLASSIFY_SYSTEM, CLASSIFY_USER.format(body=body[:6000]), 24)
		parsed = _extract_json(str(raw or ""))
		if parsed:
			score = parsed.get("category_score")
			if score is None:
				score = 0.5
			return max(0.0, min(1.0, float(score)))
	except Exception:
		pass
	return None


def _category_from_score(score: float) -> str:
	"""Ratio (1=work) → colección destino según el umbral configurable."""
	threshold = _polaroid_cfg(0.5, "MEMENTO_CATEGORY_WORK_THRESHOLD")
	return "work" if float(score) >= threshold else "social"


def _candidate_category(fm: Dict[str, Any], body: str) -> str:
	"""Categoría work/social de un refine/anotación (mismo criterio que el ascenso).

	Prioridad: `dual_route` (annotate, MEM-006) → `category_score` (refine) →
	heurística.
	"""
	route = str(fm.get("dual_route") or "").strip().lower()
	if route in ("work", "social"):
		return route
	score = fm.get("category_score")
	if score is not None:
		try:
			return _category_from_score(float(score))
		except Exception:
			pass
	from red_pill.metabolism.categorizer import detect_category_heuristics

	return detect_category_heuristics(body)


def _session_created_at(registry: Any, source: str, session_id: str) -> Optional[float]:
	"""Fecha REAL de la sesión (epoch) desde el registry, o None si no consta.

	El engrama ascendido debe llevar `created_at` = fecha de la sesión (no la de
	ascensión): es lo que ordena el hilo de Ariadna. El registry guarda ISO.
	"""
	try:
		state = getattr(registry, "state", None) or {}
		entry = (state.get("registry", {}).get(source, {}) or {}).get(session_id, {})
		iso = entry.get("created_at")
		if not iso:
			return None
		return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
	except Exception:
		return None


def ascender(
	root: Path,
	registry: Any,
	refine_path: Path,
	*,
	collection: Optional[str] = None,
	force: bool = False,
	memory_manager: Any = None,
	transport: Any = None,
) -> Dict[str, Any]:
	"""Promociona un `refine/*.md` a engrama curado en `work_memories`/`social_memories`.

	- `collection`: destino explícito; si es None, se resuelve en este orden:
	1) `category_score` del frontmatter (etiqueta ratio del curador LLM en refine);
	2) LLM on-the-fly (`transport`) para refine sin etiqueta;
	3) fallback: heurística `detect_category_heuristics` (R1).
	- `force`: re-promueve aunque el refine ya esté sellado como ascendido.
	- `memory_manager`: inyectable para tests (default `MemoryManager()`).
	- `transport`: para clasificar por LLM (Fase 4, decisión 2026-09-14).

	Devuelve un dict con `ascended` (bool), `reason`, `collection`, `point_id`.
	"""
	refine_path = Path(refine_path)
	text = refine_path.read_text(encoding="utf-8")
	fm, body = parse_refine(text)
	if not body:
		return {"ascended": False, "reason": "empty_body"}

	session_id = str(fm.get("session_id") or "")
	source_lines = str(fm.get("source_lines") or "")
	if not session_id or not source_lines:
		return {"ascended": False, "reason": "missing_key"}

	if fm.get("ascended") and not force:
		return {"ascended": False, "reason": "already_ascended", "point_id": fm.get("ascended_point_id")}

	significance = float(fm.get("significance", 0.0) or 0.0)
	emotion = str(fm.get("emotion", "gray"))
	intensity = float(fm.get("intensity", 0.0) or 0.0)
	texture = fm.get("texture") if isinstance(fm.get("texture"), dict) else {}
	theme = str(texture.get("theme", "")) if texture else ""
	relics = list(texture.get("relics", [])) if texture else []
	cross_refs = list(fm.get("cross_refs", []) or [])
	source = str(fm.get("source") or "")

	score = fm.get("category_score")
	dual_route = str(fm.get("dual_route") or "").strip().lower()
	if collection is None:
		# La clasificación vive EN el refine/anotación (category_score del curador,
		# verificado 2026-09-14: técnico → 0.8; dual_route en annotate, MEM-006).
		# El ascenso NO llama al LLM: usa la etiqueta o la heurística R1 (fallback).
		if dual_route == "none":
			return {"ascended": False, "reason": "dual_route_none"}
		if dual_route in ("work", "social"):
			category = dual_route
		elif score is not None:
			category = _category_from_score(float(score))
		else:
			from red_pill.metabolism.categorizer import detect_category_heuristics

			category = detect_category_heuristics(body)
		collection = f"{category}_memories"

	point_id = refine_point_id(session_id, source_lines, refine_path.stem)

	if memory_manager is None:
		from red_pill.memory import MemoryManager

		memory_manager = MemoryManager()

	# La colección destino puede no existir aún (p.ej. un host sin sueño previo):
	# el gate de escritura lo rechazaría. Asegurarla es idempotente y barato.
	try:
		if not memory_manager.client.collection_exists(collection):
			memory_manager._ensure_collection(collection)
	except Exception:
		pass

	metadata: Dict[str, Any] = {
		"session_id": session_id,
		"source": source,
		"source_lines": source_lines,
		"significance": significance,
		"theme": theme,
		"relics": relics,
		"cross_refs": cross_refs,
		"origin": "memento",
		"node_type": "memento_engram",
		"ascended_at": datetime.now(timezone.utc).isoformat(),
		"last_reinforced_at": time.time(),
		"refine_ref": _relative_refine_ref(root, refine_path),
		# Parámetros de la idea (2026-09-15): se guardan en el engrama para poder
		# filtrar/purgar después (p.ej. bajar el umbral y purgar los engramas con
		# significance baja, o saber con qué modelo/versión de prompt se curó).
		"emotion": emotion,
		"intensity": round(intensity, 2),
		"engine": str(fm.get("engine") or ""),
		"prompt_version": str(fm.get("prompt_version") or ""),
	}
	if score is not None:
		metadata["category_score"] = round(float(score), 2)
	for axis in ("work_score", "social_score"):
		val = fm.get(axis)
		if val is not None:
			try:
				metadata[axis] = round(float(val), 2)
			except (TypeError, ValueError):
				pass
	if dual_route in ("work", "social", "none"):
		metadata["dual_route"] = dual_route
	if fm.get("quality_flags"):
		metadata["quality_flags"] = list(fm.get("quality_flags") or [])

	new_id = memory_manager.add_memory(
		collection=collection,
		text=body,
		importance=_curated_importance(significance),
		metadata=metadata,
		point_id=point_id,
		emotion=emotion,
		intensity=intensity,
		created_at=_session_created_at(registry, source, session_id),
	)
	if not new_id:
		# El quality gate (`is_garbage`) o un fallo de escritura lo rechazó.
		logger.warning(f"[ASCENSION] refine rechazado por el gate: {refine_path.name} → {collection}")
		return {"ascended": False, "reason": "rejected", "collection": collection}

	# Sello in-place en el frontmatter del refine (no mueve el cuerpo).
	_stamp_refine(
		refine_path,
		{
			"ascended": True,
			"ascended_at": datetime.now(timezone.utc).isoformat(),
			"ascended_to": collection,
			"ascended_point_id": point_id,
		},
	)

	if source:
		registry.upsert(
			source,
			session_id,
			{"ascended": True, "ascended_to": collection, "ascended_point_id": point_id},
		)

	logger.info(f"[ASCENSION] {refine_path.name} → {collection} (point {point_id[:8]}…)")
	return {"ascended": True, "reason": "ok", "collection": collection, "point_id": point_id}
