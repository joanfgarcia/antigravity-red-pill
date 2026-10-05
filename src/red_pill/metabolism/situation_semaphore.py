"""Semáforo de situación por afinidad (single-writer D9/D20/D25).

`interaction_memories` es un buffer efímero; el semáforo es lo que se inyecta.
Por cada `affinity` se mantiene un resumen **rodante tipo solera** en
`situation_memories`: `situation_new = merge(situation_old, delta)` con peso
configurable (`SITUATION_SOLERA_RATIO`, propuesto 20/80). Dos ejes: *situación del
proyecto* (scoped por afinidad) + *mood* (global en la afinidad "global").

Actualización incremental (solo turnos nuevos desde `window_start`), ligera, con
`affinity` como clave. Todo tras `SW_SITUATION_ENABLED`; el destilado es inyectable
(por defecto, LLM local vía ProviderRegistry).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import red_pill.config as cfg

logger = logging.getLogger(__name__)

_NS = uuid.NAMESPACE_OID
COLLECTION = "situation_memories"
GLOBAL_AFFINITY = "global"

# Margen bajo el tope del esquema (MAX_METADATA_STR) para el merge solera: el
# valor escrito SIEMPRE debe pasar `CreateEngramRequest.validate_metadata_structure`.
_META_MARGIN = 10


def _meta_limit() -> int:
	"""Tope efectivo para strings de metadata (deriva del esquema, única fuente)."""
	return max(1, int(cfg.MAX_METADATA_STR) - _META_MARGIN)


def _meta_str(value: Any, limit: int) -> str:
	text = str(value or "")
	return text if len(text) <= limit else text[:limit]


def _json_counts_capped(counts: Dict[str, Any], limit: int) -> str:
	"""JSON de recuentos que cabe en `limit`: descarta las claves menos frecuentes."""
	entries = sorted(counts.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
	while entries:
		dumped = json.dumps(dict(entries), ensure_ascii=False)
		if len(dumped) <= limit:
			return dumped
		entries.pop()
	return "{}"


# Chroma para las etiquetas del tag RFC-004 (taxonomía propia; NO la del modelo
# de emociones local). Necesario porque `add_memory` puede re-detectar `emotion`
# cuando mood coincide con DEFAULT_EMOTION ("neutral") — el `color` explícito no
# se pisa si difiere del default, y es lo que puntúa el pre-heating.
TAG_EMOTION_CHROMA = {
	"calm": "cyan",
	"neutral": "gray",
	"positive": "yellow",
	"tense": "purple",
	"frustrated": "red",
	"sad": "blue",
	"focused": "emerald",
}


def situation_point_id(affinity: str) -> str:
	return str(uuid.uuid5(_NS, f"situation:{affinity}"))


def _default_distiller(text: str) -> Dict[str, Any]:
	"""Destilado ligero del estado (LLM local). Devuelve {situation, emotion, intensity}."""
	from red_pill.core.providers import ProviderRegistry

	prompt = (
		"Resume en UNA frase el ESTADO actual de este trabajo (qué se está haciendo/preguntando) "
		' y el tono del operador. Responde SOLO JSON: {"situation":"...","emotion":"gray","intensity":0.5}\n\n' + text[:4000]
	)
	try:
		provider = ProviderRegistry.get_inference_provider()
		data = json.loads(provider.generate(prompt))
		return {
			"situation": str(data.get("situation", ""))[:500],
			"emotion": str(data.get("emotion", "gray")),
			"intensity": float(data.get("intensity", 0.5)),
		}
	except Exception as e:
		logger.warning(f"[SITUATION] distiller falló: {e}")
		return {"situation": "", "emotion": "gray", "intensity": 0.5}


def aggregate_tags(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
	"""Agrega los tags RFC-004 de los turnos (`ok`/`degraded` con emoción).

	Puro (sin I/O) para test. Devuelve None si no hay NI UN turno etiquetado →
	el llamante NO consume la ventana (ausencia de dato, no fallback: no se
	inventa situación sin señal). El mood es la emoción de mayor peso por
	confianza acumulada (conteo como desempate)."""
	from collections import Counter

	tagged = [it for it in items if str(it.get("tag_status") or "") in ("ok", "degraded") and it.get("tag_emotion")]
	if not tagged:
		return None
	total = len([it for it in items if str(it.get("content") or "").strip()]) or len(items)
	emo_count: Counter = Counter()
	emo_weight: dict[str, float] = {}
	themes: Counter = Counter()
	confs: List[float] = []
	for it in tagged:
		emo = str(it["tag_emotion"])
		raw = it.get("tag_confidence")
		if raw is None:
			c = 0.5
		else:
			try:
				c = float(raw)
			except (TypeError, ValueError):
				c = 0.5
		emo_count[emo] += 1
		emo_weight[emo] = emo_weight.get(emo, 0.0) + c
		confs.append(c)
		themes[_meta_str(it.get("tag_theme") or "?", 120)] += 1
	mood = max(emo_count, key=lambda k: (emo_weight[k], emo_count[k]))
	theme = themes.most_common(1)[0][0]
	conf = sum(confs) / len(confs)
	return {
		"mood": mood,
		"theme": theme,
		"descriptor": f"{theme} · {mood} (n={len(tagged)})",
		"confidence": round(conf, 3),
		"n": len(tagged),
		"coverage": round(len(tagged) / max(1, total), 3),
		"theme_counts": dict(themes),
		"emotion_counts": dict(emo_count),
	}


def _default_merger(old: str, delta: str, ratio: float) -> str:
	"""Solera: lo previo DOMINA (1-ratio) e integra lo nuevo (ratio) sin desplazarlo.

	`ratio` = peso de lo NUEVO (0.2 = 20% nuevo / 80% previo, D20/D25). Un delta
	vacío NO degrada el resumen previo.
	"""
	limit = _meta_limit()
	old = (old or "").strip()
	delta = (delta or "").strip()
	if not delta:
		return old[:limit]
	if not old:
		return delta[:limit]
	r = max(0.0, min(1.0, ratio))
	old_budget = int(limit * (1 - r))
	new_budget = int(limit * r)
	return (old[:old_budget].rstrip() + " " + delta[:new_budget]).strip()[:limit]


def _upsert_semaphore(memory_manager: Any, aff: str, new_items: List[Dict[str, Any]], distiller: Callable, merger: Callable, ratio: float) -> bool:
	client = memory_manager.client
	pid = situation_point_id(aff)
	has_coll = client.collection_exists(COLLECTION)
	prev = client.retrieve(COLLECTION, ids=[pid]) if has_coll else []
	old_payload = (prev[0].payload or {}) if prev else {}
	window = float(old_payload.get("window_start", 0) or 0)
	fresh = [it for it in new_items if float(it["ts"]) > window]
	if not fresh:
		return False

	# Dos modos (RFC-004 §2.3): con tags (flag ON) la solera promedia tags; sin
	# tags (flag OFF) mantiene el destilado LLM. NO hay fallback tag→LLM: si el
	# modo tag está activo y no hay turnos etiquetados, no se actualiza (más
	# vale no actualizar que inventar la situación con el LLM).
	tag_mode = bool(getattr(cfg, "MEMENTO_REALTIME_TAG_ENABLED", False))
	limit = _meta_limit()
	extra_meta: Dict[str, Any] = {}
	tag_color = None
	if tag_mode:
		agg = aggregate_tags(fresh)
		if agg is None:
			return False
		recent = str(agg["descriptor"]).strip()
		mood = str(agg["mood"])
		intensity = float(agg["confidence"])
		# El chroma lleva la señal del tag de forma fiable: `add_memory` puede
		# re-detectar `emotion` si coincide con DEFAULT_EMOTION ("neutral") — el
		# color explícito NO se pisa si no es el default, y es lo que puntúa el
		# pre-heating. `mood` (y `tag_mood`) quedan como fuente autoritativa.
		tag_color = TAG_EMOTION_CHROMA.get(mood, cfg.DEFAULT_COLOR)
		# El esquema de metadata RECHAZA dicts anidados (salvo associations/
		# emotional_vector): los recuentos van como JSON en string.
		extra_meta = {
			"tag_mode": True,
			"tag_theme": _meta_str(agg["theme"], limit),
			"tag_mood": agg["mood"],
			"tag_themes_json": _json_counts_capped(agg["theme_counts"], limit),
			"tag_emotions_json": _json_counts_capped(agg["emotion_counts"], limit),
			"tagged_n": agg["n"],
			"tag_coverage": agg["coverage"],
		}
	else:
		text = "\n".join(str(it["content"]) for it in fresh)
		delta = distiller(text)
		recent = str(delta.get("situation", "")).strip()
		if not recent:
			# Destilado vacío (LLM caído): NO consumir los turnos (reintento).
			return False
		mood = str(delta.get("emotion", "gray"))
		intensity = float(delta.get("intensity", 0.5))
	# D25: dos capas — `situation_stable` (integra lo nuevo con peso ratio, decae
	# lento) + `situation_recent` (el último delta, volátil). `situation` = estable
	# (compatibilidad con el pre-heating).
	stable_old = str(old_payload.get("situation_stable") or old_payload.get("situation", ""))
	# Cinturón y tirantes: el merger por defecto ya deriva del límite, pero un
	# merger inyectado (tests/custom) no puede colar un valor que el esquema rechace.
	new_situation = _meta_str(merger(stable_old, recent, ratio), limit)
	recent = _meta_str(recent, limit)
	new_id = memory_manager.add_memory(
		collection=COLLECTION,
		text=new_situation or aff,
		metadata={
			"affinity": aff,
			"situation": new_situation,
			"situation_stable": new_situation,
			"situation_recent": recent,
			"mood": mood,
			"node_type": "situation_semaphore",
			"updated_at": time.time(),
			"window_start": max(float(it["ts"]) for it in fresh),
			**extra_meta,
		},
		point_id=pid,
		emotion=mood,
		intensity=intensity,
		color=tag_color if tag_color else cfg.DEFAULT_COLOR,
	)
	if tag_mode and new_id:
		# `add_memory` re-detecta `emotion` cuando coincide con DEFAULT_EMOTION
		# ("neutral") y eso arrastra también el chroma a uno detectado del texto.
		# Forzamos el payload a la señal del tag (fuente autoritativa) tras el
		# alta. Escritura barata (1 por actualización de solera).
		try:
			client.set_payload(
				collection_name=COLLECTION,
				payload={"emotion": mood, "color": tag_color or cfg.DEFAULT_COLOR, "intensity": intensity},
				points=[pid],
			)
		except Exception as e:
			logger.warning(f"[SITUATION] no se pudo fijar el tag en el payload: {e}")
	return bool(new_id)


def update_situation(
	memory_manager: Any,
	distiller: Optional[Callable[[str], Dict[str, Any]]] = None,
	merger: Optional[Callable[[str, str, float], str]] = None,
) -> Dict[str, Any]:
	"""Actualiza el semáforo de situación GLOBAL desde los turnos nuevos (AD-034/D15).

	Sin bucket por afinidad: la afinidad por filesystem se retiró (no refleja cómo
	trabajamos) y el semáforo es una lectura de situación, no navegación. Un único
	semáforo (`affinity="global"`) que el pre-heating inyecta.
	"""
	if not bool(getattr(cfg, "SW_SITUATION_ENABLED", False)):
		return {"enabled": False, "updated": 0}

	distiller = distiller or _default_distiller
	merger = merger or _default_merger
	ratio = float(getattr(cfg, "SITUATION_SOLERA_RATIO", 0.2))
	client = memory_manager.client
	if not client.collection_exists("interaction_memories"):
		return {"enabled": True, "updated": 0}

	# Asegura `situation_memories`: no la crea nadie más y `add_memory` no la
	# auto-crea (solo `record_interaction_pair`).
	if not client.collection_exists(COLLECTION):
		try:
			memory_manager._ensure_collection(COLLECTION)
		except Exception as e:
			logger.warning(f"[SITUATION] no se pudo crear {COLLECTION}: {e}")
			return {"enabled": True, "updated": 0}

	turns, _ = client.scroll("interaction_memories", limit=2000, with_payload=True)
	all_items = [
		{
			"content": (t.payload or {}).get("content") or "",
			"ts": (t.payload or {}).get("timestamp", 0),
			# RFC-004: los tags se agregan por solera (modo tag) sin destilar texto.
			"tag_status": (t.payload or {}).get("tag_status"),
			"tag_emotion": (t.payload or {}).get("tag_emotion"),
			"tag_theme": (t.payload or {}).get("tag_theme"),
			"tag_confidence": (t.payload or {}).get("tag_confidence"),
		}
		for t in turns
	]
	updated = 1 if _upsert_semaphore(memory_manager, GLOBAL_AFFINITY, all_items, distiller, merger, ratio) else 0
	evict_situation(memory_manager)
	return {"enabled": True, "updated": updated}


def evict_situation(memory_manager: Any) -> int:
	"""Evicta semáforos inactivos (> SITUATION_TTL_DAYS)."""
	client = memory_manager.client
	if not client.collection_exists(COLLECTION):
		return 0
	from qdrant_client import models as _m

	cutoff = time.time() - int(getattr(cfg, "SITUATION_TTL_DAYS", 30)) * 86400
	flt = _m.Filter(must=[_m.FieldCondition(key="updated_at", range=_m.Range(lt=cutoff))])
	try:
		res, _ = client.scroll(COLLECTION, scroll_filter=flt, limit=1000, with_payload=False)
		ids = [str(p.id) for p in res]
		if ids:
			client.delete(COLLECTION, points_selector=_m.PointIdsList(points=ids), wait=True)  # type: ignore[arg-type]
		return len(ids)
	except Exception as e:
		logger.warning(f"[SITUATION] evicción falló: {e}")
		return 0
