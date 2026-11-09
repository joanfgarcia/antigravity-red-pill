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
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import red_pill.config as cfg

logger = logging.getLogger(__name__)

_NS = uuid.NAMESPACE_OID
HUB_NODE_TYPE = "synthesis_hub"

# Nodo de contenido: ascendido de Memento (o legacy sin node_type). Nunca un hub.
_CONTENT_NODE_TYPES = (None, "memento_engram")

# Versión del algoritmo de síntesis que escribió el hub. Sube cuando cambie el
# contrato (v2 = map-reduce jerárquico); sirve para auditar hubs viejos.
HUB_SYNTH_VERSION = 2


def hub_point_id(collection: str, session_id: str) -> str:
	"""Id determinista del hub de sesión (idempotencia por upsert)."""
	return str(uuid.uuid5(_NS, f"hub:{collection}:{session_id}"))


def hub_input_hash(member_ids: List[Any]) -> str:
	"""Hash del conjunto de miembros (ids ordenados) → detecta cambios sin LLM."""
	return hashlib.sha256("\x00".join(sorted(str(i) for i in member_ids)).encode("utf-8")).hexdigest()


def is_hub_node(payload: Dict[str, Any]) -> bool:
	"""El punto es un hub de síntesis (marcado por fase Lazarus o por `node_type`)."""
	return payload.get("lazarus_phase") == HUB_NODE_TYPE or payload.get("node_type") == HUB_NODE_TYPE


def is_content_node(payload: Dict[str, Any]) -> bool:
	"""Engrama de contenido agrupable en un hub: Memento o legacy sin `node_type`; nunca un hub.

	Predicado único: lo usan la síntesis (qué se agrupa) y la observabilidad D26
	(sobre qué se mide la cobertura), para que numerador y denominador casen.
	"""
	if is_hub_node(payload):
		return False
	return payload.get("node_type") in _CONTENT_NODE_TYPES or payload.get("origin") == "memento"


def is_groupable(payload: Dict[str, Any]) -> bool:
	"""Contenido que la síntesis PUEDE agrupar: contenido con `session_id`.

	Es el denominador honesto de la cobertura D26: un legacy sin sesión nunca
	entrará en un hub, así que contarlo hundiría la cobertura (falsa alarma).
	"""
	return is_content_node(payload) and bool(payload.get("session_id"))


def _chrono_key(member: Tuple[Any, Dict[str, Any]]) -> Tuple[float, str]:
	"""Orden cronológico de los miembros (created_at; desempate estable por id)."""
	pid, payload = member
	try:
		ts = float((payload or {}).get("created_at") or 0.0)
	except (TypeError, ValueError):
		ts = 0.0
	return (ts, str(pid))


def group_by_session(points: List[Tuple[Any, Dict[str, Any]]]) -> Dict[str, List[Tuple[Any, Dict[str, Any]]]]:
	"""Agrupa engramas de contenido por `session_id` (excluye hubs y sin sesión).

	Los miembros se devuelven ORDENADOS por `created_at`: el map-reduce trocea
	"fragmentos cronológicos" y los rangos de navegación se calculan sobre ese
	orden, así que el orden de scroll de Qdrant (por id) no sirve.
	"""
	groups: Dict[str, List[Tuple[Any, Dict[str, Any]]]] = {}
	for pid, payload in points:
		payload = payload or {}
		if not is_groupable(payload):
			continue
		groups.setdefault(str(payload["session_id"]), []).append((pid, payload))
	for members in groups.values():
		members.sort(key=_chrono_key)
	return groups


def _members_to_chunks(members: List[Tuple[Any, Dict[str, Any]]]) -> List[Dict[str, Any]]:
	chunks: List[Dict[str, Any]] = []
	for member_index, (_pid, pl) in enumerate(members):
		texture = ""
		if pl.get("texture"):
			texture = str(pl["texture"]).strip()
		elif pl.get("theme") or pl.get("relics"):
			bits: List[str] = []
			if pl.get("theme"):
				bits.append(f"theme: {pl['theme']}")
			if pl.get("relics"):
				bits.append("relics: " + "; ".join(str(r) for r in pl["relics"]))
			texture = " | ".join(bits)
		chunks.append(
			{
				"summary": str(pl.get("content") or ""),
				"emotion": pl.get("emotion", "neutral"),
				"intensity": pl.get("intensity", 0.5),
				"texture": texture or None,
				"relics": pl.get("relics") or [],
				"lang": pl.get("lang"),
				"_member_index": member_index,
			}
		)
	return chunks


def _session_created_at(members: List[Tuple[Any, Dict[str, Any]]]) -> Optional[float]:
	vals = [float(pl["created_at"]) for _pid, pl in members if isinstance(pl.get("created_at"), (int, float))]
	return min(vals) if vals else None


def _synthesize_one(
	memory_manager: Any,
	collection: str,
	session_id: str,
	members: List[Tuple[Any, Dict[str, Any]]],
	synthesizer: Callable,
	affect_fn: Callable,
	force: bool = False,
) -> str:
	"""Escribe (upsert) el hub de un grupo de sesión y marca sus miembros.

	`force=True` salta el atajo de idempotencia: lo usa la re-síntesis de hubs
	truncados (el conjunto de miembros no cambia, pero el algoritmo sí).
	"""
	members = sorted(members, key=_chrono_key)
	member_ids = [pid for pid, _ in members]
	hid = hub_point_id(collection, session_id)
	ihash = hub_input_hash(member_ids)

	# Idempotencia: si el hub ya existe con el mismo input, no se re-sintetiza.
	if not force:
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
	hub = synthesizer(chunks, cache_namespace=f"{collection}:{session_id}") or {}
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
		"hub_members_count": len(member_ids),
		"hub_snapshot_ts": time.time(),
		"last_reinforced_at": time.time(),
	}
	# Textura: si cabe, campo canónico; si se partió (síntesis o lossless), la
	# lista `texture_parts` conserva TODO el contenido y `texture` queda vacío.
	texture = str(hub.get("texture") or "").strip()
	if texture:
		metadata["texture"] = texture
	texture_parts = [str(p).strip() for p in (hub.get("texture_parts") or []) if str(p).strip()]
	if texture_parts:
		metadata["texture_parts"] = texture_parts
		metadata["hub_texture_split"] = True
	if hub.get("lang"):
		metadata["lang"] = hub["lang"]
	if hub.get("hierarchical"):
		metadata["hub_hierarchical"] = True
		metadata["hub_partition_count"] = int(hub.get("partition_count") or 0)
		# Navegación barata (AD-116): lista plana [from0,to0,from1,to1,...]
		# sobre los miembros ordenados por created_at. Sin texto duplicado.
		flat_ranges: List[int] = []
		for rng in hub.get("partition_ranges") or []:
			if isinstance(rng, (list, tuple)) and len(rng) == 2:
				flat_ranges.extend([int(rng[0]), int(rng[1])])
		if flat_ranges:
			metadata["hub_partition_ranges"] = flat_ranges
		metadata["hub_map_reduce_levels"] = int(hub.get("map_reduce_levels") or 0)
	metadata["hub_truncated"] = bool(hub.get("truncated", False))
	metadata["hub_input_chars"] = int(hub.get("input_chars") or 0)
	metadata["hub_summary_compacted"] = bool(hub.get("summary_compacted", False))
	metadata["hub_summary_over_budget"] = bool(hub.get("summary_over_budget", False))
	metadata["hub_title_over_target"] = bool(hub.get("title_over_target", False))
	metadata["hub_texture_over_target"] = bool(hub.get("texture_over_target", False))
	metadata["hub_texture_compacted"] = bool(hub.get("texture_compacted", False))
	metadata["hub_texture_split"] = bool(hub.get("texture_split", False) or texture_parts)
	metadata["hub_texture_split_fallback"] = bool(hub.get("texture_split_fallback", False))
	metadata["hub_output_chars"] = int(hub.get("output_chars") or 0)
	metadata["hub_compaction_calls"] = int(hub.get("compaction_calls") or 0)
	metadata["hub_compaction_latency_s"] = float(hub.get("compaction_latency_s") or 0.0)
	metadata["hub_partial_cache_hits"] = int(hub.get("partial_cache_hits") or 0)
	metadata["hub_partial_cache_total"] = int(hub.get("partial_cache_total") or 0)
	# Híbrido (AD-115): modelo/prompt efectivos del maestro en hubs grandes.
	metadata["hub_large_path"] = bool(hub.get("large_path", False))
	metadata["hub_model"] = str(hub.get("model") or "")
	metadata["hub_prompt_file"] = str(hub.get("prompt_file") or "")
	metadata["hub_synth_version"] = HUB_SYNTH_VERSION
	try:
		from red_pill.metabolism.distiller import merge_relics

		relics = merge_relics(chunks)
		if relics:
			metadata["relics"] = relics
	except Exception:
		pass

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
	_clear_rebuild_pending(memory_manager, collection, session_id, hid)
	return "written"


def _mark_members(memory_manager: Any, collection: str, members: List[Tuple[Any, Dict[str, Any]]], hub_id: str) -> None:
	ids = [pid for pid, _ in members]
	if not ids:
		return
	try:
		memory_manager.client.set_payload(collection_name=collection, payload={"hubbed": True, "hub_id": hub_id}, points=ids)
	except Exception as e:
		logger.warning(f"[HUBS] no se pudieron marcar miembros en {collection}: {e}")


def _clear_rebuild_pending(memory_manager: Any, collection: str, session_id: str, hub_id: str) -> None:
	"""Consume el marcador legado `hub_rebuild_pending` al escribir el hub real.

	AD-023 §4: el flag solo se retira cuando existe una síntesis real del hub.
	Es best-effort: si el marcador no existe (caso normal hoy) no hace nada.
	"""
	try:
		from qdrant_client import models as qm

		flt = qm.Filter(
			must=[
				qm.FieldCondition(key="session_id", match=qm.MatchValue(value=session_id)),
				qm.FieldCondition(key="hub_rebuild_pending", match=qm.MatchValue(value=True)),
			]
		)
		points, _ = memory_manager.client.scroll(
			collection_name=collection, scroll_filter=flt, limit=64, with_payload=False, with_vectors=False
		)
		ids = [p.id for p in points]
		if ids:
			memory_manager.client.set_payload(
				collection_name=collection, payload={"hub_rebuild_pending": False, "hub_rebuilt_by": hub_id}, points=ids
			)
			logger.info(f"[HUBS] hub_rebuild_pending consumido en {collection}:{session_id} ({len(ids)} punto(s)).")
	except Exception as e:
		logger.debug(f"[HUBS] no se pudo consumir hub_rebuild_pending en {collection}:{session_id}: {e}")


def synthesize_session_hubs(
	memory_manager: Any,
	collections: Tuple[str, ...] = ("work_memories", "social_memories"),
	limit_sessions: Optional[int] = None,
	synthesizer: Optional[Callable] = None,
	affect_fn: Optional[Callable] = None,
	force_sessions: Optional[Set[str]] = None,
) -> Dict[str, Any]:
	"""Sintetiza hubs de sesión sobre engramas existentes (tras SW_HUBS_ENABLED).

	`force_sessions` re-sintetiza SOLO esas sesiones aunque su `hub_input_hash`
	no haya cambiado (remediación de hubs truncados por el cap viejo).
	"""
	if not bool(getattr(cfg, "SW_HUBS_ENABLED", False)):
		return {"hubs_written": 0, "hubs_skipped": 0, "hubs_failed": 0, "sessions": 0, "enabled": False}

	if synthesizer is None or affect_fn is None:
		from red_pill.metabolism.distiller import derive_hub_affect, synthesize_hub_v2

		synthesizer = synthesizer or synthesize_hub_v2
		affect_fn = affect_fn or derive_hub_affect

	stats = {"hubs_written": 0, "hubs_skipped": 0, "hubs_failed": 0, "sessions": 0, "enabled": True}
	failed_sessions: List[str] = []
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
		except Exception as e:
			logger.error(f"[HUBS] no se pudo inventariar {collection}: {e}")
			continue
		for i, (session_id, members) in enumerate(groups.items()):
			if limit_sessions is not None and i >= limit_sessions:
				break
			if len(members) < 2:
				# Hub de una sola idea: el engrama ya es buscable; no se
				# parafrasea ni se oculta (evita perder precisión).
				continue
			stats["sessions"] += 1
			force = bool(force_sessions and session_id in force_sessions)
			# Fail-soft POR SESIÓN: un hub malo no puede abortar la colección
			# (incidente 2026-11-09: una textura fuera de esquema se llevó por
			# delante 7 grupos pendientes).
			try:
				result = _synthesize_one(memory_manager, collection, session_id, members, synthesizer, affect_fn, force=force)
			except Exception as e:
				logger.error(f"[HUBS] fallo sintetizando hub {collection}:{session_id}: {e}")
				stats["hubs_failed"] += 1
				failed_sessions.append(f"{collection}:{session_id}")
				continue
			if result == "written":
				stats["hubs_written"] += 1
			elif result == "failed":
				stats["hubs_failed"] += 1
				failed_sessions.append(f"{collection}:{session_id}")
			else:
				stats["hubs_skipped"] += 1
	if stats["hubs_failed"]:
		_emit_hub_failure_signal(memory_manager, stats, failed_sessions)
	return stats


def _emit_hub_failure_signal(memory_manager: Any, stats: Dict[str, Any], failed_sessions: List[str]) -> None:
	"""Señal de dolor si algún hub no se pudo escribir (antes era invisible).

	Nunca lanza: la fase de sueño debe terminar aunque el aviso falle.
	"""
	try:
		name = "hub_synthesis_failed"
		if memory_manager.has_signal(name):
			return
		muestra = ", ".join(failed_sessions[:5])
		memory_manager.inject_signal(
			name=name,
			intensity=5.0,
			signal_type="pain",
			source="sleep/consolidation",
			criticality="WARNING",
			message=(
				f"{stats['hubs_failed']} hub(s) no se escribieron; sus miembros siguen recallables "
				f"(sin pérdida). Sesiones: {muestra}"
			),
		)
	except Exception as e:
		logger.debug(f"[HUBS] no se pudo emitir la señal de fallo: {e}")


# ── Remediation: re-síntesis de hubs truncados ───────────────────────────────


def _load_session_members(memory_manager: Any, collection: str, session_id: str) -> List[Tuple[Any, Dict[str, Any]]]:
	"""Miembros agrupables de UNA sesión (scroll filtrado; no barre la colección)."""
	from qdrant_client import models as qm

	flt = qm.Filter(must=[qm.FieldCondition(key="session_id", match=qm.MatchValue(value=session_id))])
	members: List[Tuple[Any, Dict[str, Any]]] = []
	offset = None
	while True:
		batch, offset = memory_manager.client.scroll(
			collection_name=collection,
			scroll_filter=flt,
			limit=1000,
			offset=offset,
			with_payload=True,
			with_vectors=False,
		)
		for p in batch:
			payload = p.payload or {}
			if is_groupable(payload):
				members.append((p.id, payload))
		if offset is None:
			break
	return members


def find_oversized_sessions(
	memory_manager: Any,
	collections: Tuple[str, ...] = ("work_memories", "social_memories"),
	budget: Optional[int] = None,
	only_pending: bool = True,
) -> List[Dict[str, Any]]:
	"""Sesiones cuyo prompt de hub supera el presupuesto actual (inventario).

	Read-only. Reproduce exactamente lo que `synthesize_hub_v2` enviaría hoy:
	sirve para el `--list` del job de re-síntesis y para auditar el sueño.

	`only_pending=True` (default del job) omite las sesiones cuyo hub ya se
	re-sintetizó con la versión vigente y no quedó truncado: el job es
	idempotente y reanudable sin repetir trabajo.
	"""
	from red_pill.metabolism.distiller import hub_budget, render_hub_items

	limit = int(budget or hub_budget())
	rows: List[Dict[str, Any]] = []
	for collection in collections:
		try:
			if not memory_manager.client.collection_exists(collection):
				continue
		except Exception:
			continue
		points: List[Tuple[Any, Dict[str, Any]]] = []
		offset = None
		while True:
			batch, offset = memory_manager.client.scroll(collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
			points.extend((p.id, p.payload) for p in batch)
			if offset is None:
				break
		for session_id, members in group_by_session(points).items():
			if len(members) < 2:
				continue
			chars = len(render_hub_items(_members_to_chunks(members)))
			if chars <= limit:
				continue
			if only_pending:
				try:
					existing = memory_manager.client.retrieve(collection_name=collection, ids=[hub_point_id(collection, session_id)])
					if existing:
						pl = existing[0].payload or {}
						if int(pl.get("hub_synth_version") or 0) >= HUB_SYNTH_VERSION and not bool(pl.get("hub_truncated")):
							continue
				except Exception:
					pass
			rows.append(
				{
					"collection": collection,
					"session_id": session_id,
					"members": len(members),
					"input_chars": chars,
					"over_by": chars - limit,
				}
			)
	rows.sort(key=lambda r: r["input_chars"], reverse=True)
	return rows


def resynthesize_session(memory_manager: Any, collection: str, session_id: str, force: bool = True) -> str:
	"""Re-sintetiza el hub de UNA sesión (map-reduce). Devuelve written|skipped|failed."""
	from red_pill.metabolism.distiller import derive_hub_affect, synthesize_hub_v2

	members = _load_session_members(memory_manager, collection, session_id)
	if len(members) < 2:
		return "skipped"
	return _synthesize_one(
		memory_manager, collection, session_id, members, synthesize_hub_v2, derive_hub_affect, force=force
	)


# Alias públicos para scripts/auditorías (mismo contrato, sin guion bajo).
load_session_members = _load_session_members
members_to_chunks = _members_to_chunks
