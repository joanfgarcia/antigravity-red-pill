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
	"""Solera: lo previo DOMINA (1-ratio) e integra lo nuevo (ratio) sin desplazarlo.

	`ratio` = peso de lo NUEVO (0.2 = 20% nuevo / 80% previo, D20/D25). Un delta
	vacío NO degrada el resumen previo.
	"""
	old = (old or "").strip()
	delta = (delta or "").strip()
	if not delta:
		return old[:2000]
	if not old:
		return delta[:2000]
	r = max(0.0, min(1.0, ratio))
	old_budget = int(2000 * (1 - r))
	new_budget = int(2000 * r)
	return (old[:old_budget].rstrip() + " " + delta[:new_budget]).strip()[:2000]


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
	recent = str(delta.get("situation", "")).strip()
	if not recent:
		# Destilado vacío (LLM caído): NO consumir los turnos (reintento).
		return False
	# D25: dos capas — `situation_stable` (integra lo nuevo con peso ratio, decae
	# lento) + `situation_recent` (el último delta, volátil). `situation` = estable
	# (compatibilidad con el pre-heating).
	stable_old = str(old_payload.get("situation_stable") or old_payload.get("situation", ""))
	new_situation = merger(stable_old, recent, ratio)
	new_id = memory_manager.add_memory(
		collection=COLLECTION,
		text=new_situation or aff,
		metadata={
			"affinity": aff,
			"situation": new_situation,
			"situation_stable": new_situation,
			"situation_recent": recent,
			"mood": str(delta.get("emotion", "gray")),
			"node_type": "situation_semaphore",
			"updated_at": time.time(),
			"window_start": max(float(it["ts"]) for it in fresh),
		},
		point_id=pid,
		emotion=str(delta.get("emotion", "gray")),
		intensity=float(delta.get("intensity", 0.5)),
	)
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
		{"content": (t.payload or {}).get("content") or "", "ts": (t.payload or {}).get("timestamp", 0)}
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
			client.delete(COLLECTION, points_selector=_m.PointIdsList(points=ids), wait=True)
		return len(ids)
	except Exception as e:
		logger.warning(f"[SITUATION] evicción falló: {e}")
		return 0
