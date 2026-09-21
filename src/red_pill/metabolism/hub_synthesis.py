"""Hub synthesis sobre engramas EXISTENTES (single-writer D2/D7/D14).

Sustituye la síntesis de hubs que vivía acoplada al drenaje de
`interaction_memories`: ahora agrupa los engramas curados ya presentes en Qdrant
(`node_type="memento_engram"` o `origin="memento"`) por **sesión** y sintetiza un
hub de sesión (reemplaza el `raw_parent` perdido), marcando sus miembros para que
el recall los omita (entran por el hub).

Idempotente: `point_id` determinista por sesión + `hub_input_hash` (si el conjunto
de miembros no cambió, se salta la síntesis — sin coste LLM).

Todo tras `SW_HUBS_ENABLED`. No toca los índices de fase del DAG: se invoca desde
la fase existente.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import red_pill.config as cfg

logger = logging.getLogger(__name__)

_NS = uuid.NAMESPACE_OID
HUB_NODE_TYPE = "synthesis_hub"

# Nodo de contenido: ascendido de Memento (o legacy sin node_type). Nunca un hub.
_CONTENT_NODE_TYPES = (None, "memento_engram")


def hub_point_id(collection: str, session_id: str) -> str:
	"""Id determinista del hub de sesión (idempotencia por upsert)."""
	return str(uuid.uuid5(_NS, f"hub:{collection}:{session_id}"))


def hub_input_hash(member_ids: List[Any]) -> str:
	"""Hash del conjunto de miembros (ids ordenados) → detecta cambios sin LLM."""
	return hashlib.sha256("\x00".join(sorted(str(i) for i in member_ids)).encode("utf-8")).hexdigest()


def group_by_session(points: List[Tuple[Any, Dict[str, Any]]]) -> Dict[str, List[Tuple[Any, Dict[str, Any]]]]:
	"""Agrupa engramas de contenido por `session_id` (excluye hubs y sin sesión)."""
	groups: Dict[str, List[Tuple[Any, Dict[str, Any]]]] = {}
	for pid, payload in points:
		payload = payload or {}
		if payload.get("lazarus_phase") == HUB_NODE_TYPE or payload.get("node_type") == HUB_NODE_TYPE:
			continue
		node_type = payload.get("node_type")
		if node_type not in _CONTENT_NODE_TYPES and payload.get("origin") != "memento":
			continue
		sid = str(payload.get("session_id") or "")
		if not sid:
			continue
		groups.setdefault(sid, []).append((pid, payload))
	return groups


def _members_to_chunks(members: List[Tuple[Any, Dict[str, Any]]]) -> List[Dict[str, Any]]:
	chunks: List[Dict[str, Any]] = []
	for _pid, pl in members:
		texture: Dict[str, Any] = {}
		if pl.get("theme"):
			texture["theme"] = pl["theme"]
		if pl.get("relics"):
			texture["relics"] = pl["relics"]
		chunks.append(
			{
				"summary": str(pl.get("content") or ""),
				"emotion": pl.get("emotion", "neutral"),
				"intensity": pl.get("intensity", 0.5),
				"texture": texture or None,
				"lang": pl.get("lang"),
			}
		)
	return chunks


def _session_created_at(members: List[Tuple[Any, Dict[str, Any]]]) -> Optional[float]:
	vals = [float(pl["created_at"]) for _pid, pl in members if isinstance(pl.get("created_at"), (int, float))]
	return min(vals) if vals else None


def _synthesize_one(memory_manager: Any, collection: str, session_id: str, members: List[Tuple[Any, Dict[str, Any]]], synthesizer: Callable, affect_fn: Callable) -> str:
	"""Escribe (upsert) el hub de un grupo de sesión y marca sus miembros."""
	member_ids = [pid for pid, _ in members]
	hid = hub_point_id(collection, session_id)
	ihash = hub_input_hash(member_ids)

	# Idempotencia: si el hub ya existe con el mismo input, no se re-sintetiza.
	try:
		existing = memory_manager.client.retrieve(collection_name=collection, ids=[hid])
		if existing:
			prev = (existing[0].payload or {}).get("hub_input_hash")
			if prev == ihash:
				_mark_members(memory_manager, collection, members, hid)
				return "skipped"
	except Exception:
		pass

	chunks = _members_to_chunks(members)
	hub = synthesizer(chunks) or {}
	if hub.get("_is_fallback"):
		# El sintetizador cayó al fallback mecánico (LLM caído): NO se escribe un
		# hub-basura ni se marcan miembros (quedarían ocultos sin hub real). Se
		# reintenta cuando el LLM esté disponible.
		logger.warning(f"[HUBS] síntesis fallback en {collection}:{session_id}; se omite (reintento).")
		return "failed"
	body = str(hub.get("summary") or "")
	if hub.get("title"):
		body = f"{hub['title']}\n{body}"
	emotion, intensity = affect_fn(chunks)

	metadata: Dict[str, Any] = {
		"node_type": HUB_NODE_TYPE,
		"lazarus_phase": HUB_NODE_TYPE,
		"hub_key": f"{collection}:{session_id}",
		"hub_input_hash": ihash,
		"hub_depth": 2,
		"session_id": session_id,
		"origin": "memento_hub",
		"members": member_ids,
		"last_reinforced_at": time.time(),
	}
	if hub.get("texture"):
		metadata["texture"] = hub["texture"]
	if hub.get("lang"):
		metadata["lang"] = hub["lang"]

	new_id = memory_manager.add_memory(
		collection=collection,
		text=body,
		metadata=metadata,
		point_id=hid,
		emotion=emotion,
		intensity=intensity,
		created_at=_session_created_at(members),
	)
	if not new_id:
		# Escritura rechazada (quality gate / fallo): NO marcar miembros (F3).
		logger.warning(f"[HUBS] hub rechazado al escribir en {collection}:{session_id}; miembros intactos.")
		return "failed"
	# F3: marcar los miembros SOLO tras escribir el hub CON ÉXITO.
	_mark_members(memory_manager, collection, members, hid)
	return "written"


def _mark_members(memory_manager: Any, collection: str, members: List[Tuple[Any, Dict[str, Any]]], hub_id: str) -> None:
	ids = [pid for pid, _ in members]
	if not ids:
		return
	try:
		memory_manager.client.set_payload(collection_name=collection, payload={"hubbed": True, "hub_id": hub_id}, points=ids)
	except Exception as e:
		logger.warning(f"[HUBS] no se pudieron marcar miembros en {collection}: {e}")


def synthesize_session_hubs(
	memory_manager: Any,
	collections: Tuple[str, ...] = ("work_memories", "social_memories"),
	limit_sessions: Optional[int] = None,
	synthesizer: Optional[Callable] = None,
	affect_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
	"""Sintetiza hubs de sesión sobre engramas existentes (tras SW_HUBS_ENABLED)."""
	if not bool(getattr(cfg, "SW_HUBS_ENABLED", False)):
		return {"hubs_written": 0, "hubs_skipped": 0, "hubs_failed": 0, "sessions": 0, "enabled": False}

	if synthesizer is None or affect_fn is None:
		from red_pill.metabolism.distiller import derive_hub_affect, synthesize_hub_v2

		synthesizer = synthesizer or synthesize_hub_v2
		affect_fn = affect_fn or derive_hub_affect

	stats = {"hubs_written": 0, "hubs_skipped": 0, "hubs_failed": 0, "sessions": 0, "enabled": True}
	for collection in collections:
		try:
			if not memory_manager.client.collection_exists(collection):
				continue
			points: List[Tuple[Any, Dict[str, Any]]] = []
			offset = None
			while True:
				batch, offset = memory_manager.client.scroll(collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
				points.extend((p.id, p.payload) for p in batch)
				if offset is None:
					break
			groups = group_by_session(points)
			for i, (session_id, members) in enumerate(groups.items()):
				if limit_sessions is not None and i >= limit_sessions:
					break
				if len(members) < 2:
					# Hub de una sola idea: el engrama ya es buscable; no se
					# parafrasea ni se oculta (evita perder precisión).
					continue
				stats["sessions"] += 1
				result = _synthesize_one(memory_manager, collection, session_id, members, synthesizer, affect_fn)
				if result == "written":
					stats["hubs_written"] += 1
				elif result == "failed":
					stats["hubs_failed"] += 1
				else:
					stats["hubs_skipped"] += 1
		except Exception as e:
			logger.error(f"[HUBS] fallo sintetizando hubs en {collection}: {e}")
	return stats
