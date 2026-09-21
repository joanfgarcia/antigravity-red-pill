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


def _default_merger(old: str, delta: str, ratio: float) -> str:
	"""Solera: conserva ~ratio de lo previo e integra lo nuevo sin desplazarlo."""
	if not old:
		return delta
	keep = int(len(old) * max(0.0, min(1.0, ratio)))
	return (old[:keep].rstrip() + " " + delta).strip()[:2000]


def _group_turns(turns: List[Any]) -> Dict[str, List[Dict[str, Any]]]:
	groups: Dict[str, List[Dict[str, Any]]] = {}
	for t in turns:
		pl = t.payload or {}
		meta = pl.get("metadata") or {}
		content = pl.get("content") or ""
		ts = pl.get("timestamp", 0)
		affs = meta.get("affinity") or []
		for aff in affs:
			groups.setdefault(str(aff), []).append({"content": content, "ts": ts})
	return groups


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
	text = "\n".join(str(it["content"]) for it in fresh)
	delta = distiller(text)
	new_situation = merger(str(old_payload.get("situation", "")), str(delta.get("situation", "")), ratio)
	memory_manager.add_memory(
		collection=COLLECTION,
		text=new_situation or aff,
		metadata={
			"affinity": aff,
			"situation": new_situation,
			"mood": str(delta.get("emotion", "gray")),
			"node_type": "situation_semaphore",
			"updated_at": time.time(),
			"window_start": max(float(it["ts"]) for it in fresh),
		},
		point_id=pid,
		emotion=str(delta.get("emotion", "gray")),
		intensity=float(delta.get("intensity", 0.5)),
	)
	return True


def update_situation(
	memory_manager: Any,
	distiller: Optional[Callable[[str], Dict[str, Any]]] = None,
	merger: Optional[Callable[[str, str, float], str]] = None,
) -> Dict[str, Any]:
	"""Actualiza el semáforo por afinidad (y el global de mood) desde los turnos nuevos."""
	if not bool(getattr(cfg, "SW_SITUATION_ENABLED", False)):
		return {"enabled": False, "affinities": 0}

	distiller = distiller or _default_distiller
	merger = merger or _default_merger
	ratio = float(getattr(cfg, "SITUATION_SOLERA_RATIO", 0.2))
	max_aff = int(getattr(cfg, "SITUATION_MAX_AFFINITIES_PER_CYCLE", 10))
	client = memory_manager.client
	if not client.collection_exists("interaction_memories"):
		return {"enabled": True, "affinities": 0}

	turns, _ = client.scroll("interaction_memories", limit=2000, with_payload=True)
	groups = _group_turns(turns)

	updated = 0
	for aff, items in list(groups.items())[:max_aff]:
		if _upsert_semaphore(memory_manager, aff, items, distiller, merger, ratio):
			updated += 1

	# Semáforo GLOBAL de mood (todos los turnos, cruzando sesiones).
	all_items = [{"content": (t.payload or {}).get("content") or "", "ts": (t.payload or {}).get("timestamp", 0)} for t in turns]
	if _upsert_semaphore(memory_manager, GLOBAL_AFFINITY, all_items, distiller, merger, ratio):
		updated += 1

	evict_situation(memory_manager)
	return {"enabled": True, "affinities": updated}


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
			client.delete(COLLECTION, points_selector=_m.PointIdsList(points=ids), wait=True)
		return len(ids)
	except Exception as e:
		logger.warning(f"[SITUATION] evicción falló: {e}")
		return 0
