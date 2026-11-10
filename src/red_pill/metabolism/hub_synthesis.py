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
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import red_pill.config as cfg

logger = logging.getLogger(__name__)

_NS = uuid.NAMESPACE_OID
HUB_NODE_TYPE = "synthesis_hub"

# Nodo de contenido: ascendido de Memento (o legacy sin node_type). Nunca un hub.
_CONTENT_NODE_TYPES = (None, "memento_engram")

# Versión del algoritmo de síntesis que escribió el hub. Sube cuando cambie el
# contrato (v2 = map-reduce jerárquico; v3 = índice recuperable: hub_title,
# hub_terms, scrub y orden de miembros); sirve para auditar hubs viejos.
HUB_SYNTH_VERSION = 3

# Motivos de bloqueo de migración (metadata, reversible): un hub sin >=2
# miembros no se puede re-sintetizar desde Qdrant. Se marca y se reintenta solo
# cuando una ascensión vuelve a aportar miembros (ver refresh_hub_block_state).
HUB_MIGRATION_BLOCKED_NO_MEMBERS = "no_members"
HUB_MIGRATION_BLOCKED_SINGLETON = "singleton"


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


def sort_members_chronologically(members: List[Tuple[Any, Dict[str, Any]]]) -> List[Tuple[Any, Dict[str, Any]]]:
	"""Contrato único de orden hub→miembro (D-15): `created_at`, desempate id.

	Lo usan la síntesis, `hub_members` y `traverse_thread` para que los rangos
	`hub_partition_ranges` y la navegación hablen del mismo orden.
	"""
	return sorted(members, key=_chrono_key)


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
	members = sort_members_chronologically(members)
	member_ids = [pid for pid, _ in members]
	hid = hub_point_id(collection, session_id)
	ihash = hub_input_hash(member_ids)

	# Idempotencia: si el hub ya existe con el mismo input, no se re-sintetiza.
	# Con `SW_HUB_VERSION_INVALIDATION_ENABLED` también invalida al cambiar el
	# contrato (HUB_SYNTH_VERSION). Default OFF: la migración del corpus se
	# decide aparte (D-11) y no se dispara sola en un ciclo de sueño.
	previous_payload: Dict[str, Any] = {}
	try:
		existing = memory_manager.client.retrieve(collection_name=collection, ids=[hid])
		if existing:
			previous_payload = existing[0].payload or {}
	except Exception:
		pass
	if not force and previous_payload:
		if previous_payload.get("hub_input_hash") == ihash:
			prev_version = int(previous_payload.get("hub_synth_version") or 0)
			version_ok = prev_version >= HUB_SYNTH_VERSION or not bool(
				getattr(cfg, "SW_HUB_VERSION_INVALIDATION_ENABLED", False)
			)
			if version_ok:
				# Reversible: si el hub estaba bloqueado y ahora tiene >=2
				# miembros (p.ej. tras una ascensión), se limpia el bloqueo
				# aunque el input hash no haya cambiado (skip).
				if len(member_ids) >= 2 and (
					bool(previous_payload.get("hub_migration_blocked"))
					or int(previous_payload.get("hub_members_count") or -1) != len(member_ids)
				):
					try:
						memory_manager.client.set_payload(
							collection_name=collection,
							payload={
								"hub_members_count": len(member_ids),
								"hub_migration_blocked": False,
								"hub_migration_blocked_reason": "",
								"hub_members_checked_at": time.time(),
							},
							points=[hid],
						)
					except Exception as exc:
						logger.debug(f"[HUBS] no se pudo limpiar el bloqueo de {collection}:{session_id}: {exc}")
				_mark_members(memory_manager, collection, members, hid)
				return "skipped"

	chunks = _members_to_chunks(members)
	hub = synthesizer(chunks, cache_namespace=f"{collection}:{session_id}") or {}
	if hub.get("_is_fallback"):
		# El sintetizador cayó al fallback mecánico (LLM caído): NO se escribe un
		# hub-basura ni se marcan miembros (quedarían ocultos sin hub real). Se
		# reintenta cuando el LLM esté disponible.
		logger.warning(f"[HUBS] síntesis fallback en {collection}:{session_id}; se omite (reintento).")
		return "failed"
	body = str(hub.get("summary") or "")
	# Un engrama es una IDEA, no una historia: el summary que va a Qdrant (y
	# por tanto al contexto de una búsqueda) tiene un tope duro. El detalle vive
	# en Memento (notas/polaroids/raw) y en los miembros; si el maestro no baja
	# por síntesis, NO se escribe el hub: se reintenta, no se inyectan 3k chars.
	hard_limit = max(200, int(getattr(cfg, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000) or 1000))
	if len(body) > hard_limit:
		logger.warning(
			f"[HUBS] summary {len(body)} > hard limit {hard_limit} en {collection}:{session_id}; "
			"no se escribe (se reintenta; el detalle sigue en Memento)"
		)
		return "failed"
	if hub.get("summary_lang_mismatch"):
		logger.warning(
			f"[HUBS] summary en idioma distinto al dominante en {collection}:{session_id}; "
			"no se escribe (se reintenta con reescritura)"
		)
		return "failed"
	title = str(hub.get("title") or "").strip()
	# D-12: el hub puede contener credenciales tecleadas en la sesión; se
	# redactan ANTES del upsert (idempotente, no toca el resto del texto).
	if bool(getattr(cfg, "SW_HUB_SCRUB_ENABLED", True)):
		from red_pill.memento.scrub import scrub_secrets

		body = scrub_secrets(body)
		title = scrub_secrets(title)
	if title:
		body = f"{title}\n{body}"
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
		# Estado de migración (reversible): al escribir un hub con >=2 miembros
		# se limpia cualquier bloqueo previo.
		"hub_migration_blocked": False,
		"hub_migration_blocked_reason": "",
		"hub_members_checked_at": time.time(),
		"hub_snapshot_ts": time.time(),
		"last_reinforced_at": time.time(),
	}
	# Textura: si cabe, campo canónico; si se partió (síntesis o lossless), la
	# lista `texture_parts` conserva TODO el contenido y `texture` queda vacío.
	texture = str(hub.get("texture") or "").strip()
	if bool(getattr(cfg, "SW_HUB_SCRUB_ENABLED", True)) and texture:
		from red_pill.memento.scrub import scrub_secrets

		texture = scrub_secrets(texture)
	texture_parts = [str(p).strip() for p in (hub.get("texture_parts") or []) if str(p).strip()]
	# F1 (NB-001): guard ANTES de add_memory. Un synthesizer custom puede
	# devolver una textura sin `texture_parts` que excede `MAX_METADATA_STR`; se
	# parte lossless aquí (función ya existente) para no pagar la escritura y que
	# el schema la rechace (incidente 2026-11-09 06:16). Orden de scrub: primero
	# la textura entera (arriba) y después cada parte resultante (abajo).
	guard_split = False
	if texture and not texture_parts and len(texture) > getattr(cfg, "MAX_METADATA_STR", 1024):
		from red_pill.metabolism.distiller import split_text_lossless

		texture_parts = split_text_lossless(texture, getattr(cfg, "MAX_METADATA_STR", 1024))
		texture = ""
		guard_split = True
	if texture:
		metadata["texture"] = texture
	if texture_parts and bool(getattr(cfg, "SW_HUB_SCRUB_ENABLED", True)):
		from red_pill.memento.scrub import scrub_secrets

		texture_parts = [scrub_secrets(p) for p in texture_parts]
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
		# D-09: títulos de hilo en metadata (≤20, ≤60 chars), nunca en `content`.
		partition_titles: List[str] = []
		for part in (hub.get("partitions") or [])[:20]:
			text = str(part.get("summary") or "").replace("\n", " ").strip()
			if text:
				partition_titles.append(text[:60])
		if partition_titles:
			metadata["hub_partition_titles"] = partition_titles
		metadata["hub_map_reduce_levels"] = int(hub.get("map_reduce_levels") or 0)
	metadata["hub_truncated"] = bool(hub.get("truncated", False))
	metadata["hub_input_chars"] = int(hub.get("input_chars") or 0)
	metadata["hub_summary_compacted"] = bool(hub.get("summary_compacted", False))
	metadata["hub_summary_over_budget"] = bool(hub.get("summary_over_budget", False))
	metadata["hub_summary_language_rewritten"] = bool(hub.get("summary_language_rewritten", False))
	metadata["hub_summary_lang_mismatch"] = bool(hub.get("summary_lang_mismatch", False))
	metadata["hub_title_over_target"] = bool(hub.get("title_over_target", False))
	metadata["hub_texture_over_target"] = bool(hub.get("texture_over_target", False))
	metadata["hub_texture_compacted"] = bool(hub.get("texture_compacted", False))
	metadata["hub_texture_split"] = bool(hub.get("texture_split", False) or texture_parts)
	metadata["hub_texture_split_fallback"] = bool(hub.get("texture_split_fallback", False) or guard_split)
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
	# Índice keyword del hub (HUB-RECALL-001, D-02b): anclas elegidas con
	# presupuesto blando. Se guardan como lista; el content sigue siendo la idea.
	try:
		from red_pill.memento.hub_terms import hub_terms_chars, select_hub_terms

		selected_terms = select_hub_terms(body, title=title)
		metadata["hub_title"] = title
		metadata["hub_terms"] = selected_terms
		metadata["hub_terms_chars"] = hub_terms_chars(selected_terms)
	except Exception as exc:  # nunca impedir que se escriba el hub
		logger.warning(f"[HUBS] no se pudieron calcular hub_terms en {collection}:{session_id}: {exc}")
	try:
		from red_pill.metabolism.distiller import merge_relics

		relics = merge_relics(chunks)
		if relics:
			metadata["relics"] = relics
	except Exception:
		pass

	# Re-síntesis: `add_memory` reemplaza el payload entero. Se conservan los
	# campos FUERA del contrato del hub (cadena macro de Ariadne y asociaciones)
	# para no vaciar `prev/next_session_hub` al migrar (HR-S03).
	for key in ("prev_session_hub", "next_session_hub", "associations"):
		if key not in metadata and previous_payload.get(key):
			metadata[key] = previous_payload[key]

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


def _mark_members(memory_manager: Any, collection: str, members: List[Tuple[Any, Dict[str, Any]]], hub_id: str) -> bool:
	"""Marca los miembros como agrupados. Devuelve False si Qdrant lo rechaza.

	No bloquea la escritura del hub (el fallo deja a los miembros recallables,
	que es el lado seguro), pero queda auditado para `hub_index_integrity`.
	"""
	ids = [pid for pid, _ in members]
	if not ids:
		return True
	try:
		memory_manager.client.set_payload(collection_name=collection, payload={"hubbed": True, "hub_id": hub_id}, points=ids)
		return True
	except Exception as e:
		logger.warning(f"[HUBS] no se pudieron marcar miembros en {collection}: {e}")
		return False


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


def is_stale_hub(payload: Dict[str, Any], hard_limit: Optional[int] = None) -> bool:
	"""¿El hub no cumple el contrato vigente? (v<3 o summary sobre el tope DURO).

	OJO: `hub_summary_over_budget` es el flag del TARGET (900), no del tope duro
	(1.000). Un hub v3 con 950 chars está por encima del target pero es válido;
	marcarlo stale lo haría re-sintetizar para siempre. El criterio real es
	versión y `summary_chars > hard_limit`.
	"""
	version = int(payload.get("hub_synth_version") or 0)
	if version < HUB_SYNTH_VERSION:
		return True
	limit = int(hard_limit or getattr(cfg, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000) or 1000)
	content = str(payload.get("content") or "")
	title = str(payload.get("hub_title") or "")
	# `content` = title + "\n" + summary; el hard gate se aplica al summary.
	summary_chars = max(0, len(content) - (len(title) + 1 if title and content.startswith(title + "\n") else 0))
	return summary_chars > limit


def find_stale_hubs(
	memory_manager: Any,
	collections: Tuple[str, ...] = ("work_memories", "social_memories"),
	hard_limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
	"""Inventario READ-ONLY de hubs fuera del contrato vigente (D-11: listar).

	No re-sintetiza nada. Ordena por antigüedad de versión y tamaño para que el
	Operador vea primero lo que más se aleja del contrato.
	"""
	from qdrant_client.http import models as qm

	rows: List[Dict[str, Any]] = []
	for collection in collections:
		try:
			if not memory_manager.client.collection_exists(collection):
				continue
		except Exception:
			continue
		offset = None
		while True:
			batch, offset = memory_manager.client.scroll(
				collection,
				scroll_filter=qm.Filter(
					should=[
						qm.FieldCondition(key="node_type", match=qm.MatchValue(value=HUB_NODE_TYPE)),
						qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value=HUB_NODE_TYPE)),
					]
				),
				limit=512,
				offset=offset,
				with_payload=True,
				with_vectors=False,
			)
			for point in batch:
				payload = point.payload or {}
				if not is_stale_hub(payload, hard_limit=hard_limit):
					continue
				rows.append(
					{
						"collection": collection,
						"hub_id": str(point.id),
						"session_id": payload.get("session_id"),
						"hub_synth_version": int(payload.get("hub_synth_version") or 0),
						"content_chars": len(str(payload.get("content") or "")),
						"summary_over_budget": bool(payload.get("hub_summary_over_budget")),
						"members_count": int(payload.get("hub_members_count") or 0),
						"hub_migration_blocked": bool(payload.get("hub_migration_blocked")),
						"hub_migration_blocked_reason": str(payload.get("hub_migration_blocked_reason") or ""),
					}
				)
			if offset is None:
				break
	rows.sort(key=lambda row: (row["hub_synth_version"], -row["content_chars"]))
	return rows


def _block_state(member_count: int) -> Tuple[bool, str]:
	"""Estado de bloqueo según miembros: <2 bloqueado, con motivo explícito."""
	if member_count >= 2:
		return False, ""
	if member_count == 0:
		return True, HUB_MIGRATION_BLOCKED_NO_MEMBERS
	return True, HUB_MIGRATION_BLOCKED_SINGLETON


def refresh_hub_block_state(
	memory_manager: Any,
	collection: str,
	session_id: str,
	write: bool = True,
) -> Optional[Dict[str, Any]]:
	"""Recalcula si el hub de una sesión está bloqueado y, si cambió, lo marca.

	Reversible por diseño: una ascensión (o cualquier re-promoción) de miembros
	con el mismo `session_id` vuelve a dejar `member_count>=2`, limpia el bloqueo
	y deja el hub listo para que el ciclo de sueño lo re-sintetice.
	Devuelve None si el hub no existe.
	"""
	hid = hub_point_id(collection, session_id)
	try:
		points = memory_manager.client.retrieve(collection_name=collection, ids=[hid], with_payload=True)
	except Exception:
		return None
	if not points:
		return None
	payload = points[0].payload or {}
	members = _load_session_members(memory_manager, collection, session_id)
	count = len(members)
	blocked, reason = _block_state(count)
	was_blocked = bool(payload.get("hub_migration_blocked"))
	previous_count = int(payload.get("hub_members_count") or -1)
	changed = (was_blocked != blocked) or (previous_count != count) or str(payload.get("hub_migration_blocked_reason") or "") != reason
	if write and changed:
		try:
			memory_manager.client.set_payload(
				collection_name=collection,
				payload={
					"hub_members_count": count,
					"hub_migration_blocked": blocked,
					"hub_migration_blocked_reason": reason,
					"hub_members_checked_at": time.time(),
				},
				points=[hid],
			)
		except Exception as exc:
			logger.warning(f"[HUBS] no se pudo actualizar el bloqueo de {collection}:{session_id}: {exc}")
			return None
	return {
		"collection": collection,
		"hub_id": hid,
		"session_id": session_id,
		"members": count,
		"blocked": blocked,
		"reason": reason,
		"was_blocked": was_blocked,
		"changed": changed,
	}


def reconcile_hub_blocks(
	memory_manager: Any,
	collections: Tuple[str, ...] = ("work_memories", "social_memories"),
	apply: bool = True,
) -> List[Dict[str, Any]]:
	"""Reconcilia el estado blocked/count de TODOS los hubs (una pasada por colección).

	Pensado para el ciclo de sueño y para `--mark-blocked`: detecta islas nuevas
	(erosión) y desbloquea las que han recuperado miembros (ascensión). Es
	idempotente y solo escribe cuando el estado cambia.
	"""
	from qdrant_client.http import models as qm

	rows: List[Dict[str, Any]] = []
	hub_filter = qm.Filter(
		should=[
			qm.FieldCondition(key="node_type", match=qm.MatchValue(value=HUB_NODE_TYPE)),
			qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value=HUB_NODE_TYPE)),
		]
	)
	for collection in collections:
		try:
			if not memory_manager.client.collection_exists(collection):
				continue
		except Exception:
			continue
		points: List[Tuple[Any, Dict[str, Any]]] = []
		offset = None
		while True:
			batch, offset = memory_manager.client.scroll(
				collection, limit=1000, offset=offset, with_payload=True, with_vectors=False
			)
			points.extend((p.id, p.payload or {}) for p in batch)
			if offset is None:
				break
		members_by_session: Dict[str, int] = {}
		for _pid, payload in points:
			if is_groupable(payload):
				sid = str(payload.get("session_id") or "")
				if sid:
					members_by_session[sid] = members_by_session.get(sid, 0) + 1
		hubs: List[Tuple[Any, Dict[str, Any]]] = []
		offset = None
		while True:
			batch, offset = memory_manager.client.scroll(
				collection, scroll_filter=hub_filter, limit=512, offset=offset, with_payload=True, with_vectors=False
			)
			hubs.extend((p.id, p.payload or {}) for p in batch)
			if offset is None:
				break
		for pid, payload in hubs:
			sid = str(payload.get("session_id") or "")
			if not sid:
				continue
			count = members_by_session.get(sid, 0)
			blocked, reason = _block_state(count)
			was_blocked = bool(payload.get("hub_migration_blocked"))
			previous_count = int(payload.get("hub_members_count") or -1)
			changed = (was_blocked != blocked) or (previous_count != count) or str(payload.get("hub_migration_blocked_reason") or "") != reason
			rows.append(
				{
					"collection": collection,
					"hub_id": str(pid),
					"session_id": sid,
					"members": count,
					"blocked": blocked,
					"reason": reason,
					"was_blocked": was_blocked,
					"changed": changed,
				}
			)
			if apply and changed:
				try:
					memory_manager.client.set_payload(
						collection_name=collection,
						payload={
							"hub_members_count": count,
							"hub_migration_blocked": blocked,
							"hub_migration_blocked_reason": reason,
							"hub_members_checked_at": time.time(),
						},
						points=[pid],
					)
				except Exception as exc:
					logger.warning(f"[HUBS] no se pudo reconciliar el hub {collection}:{pid}: {exc}")
	return rows


def promote_compact_hub(
	memory_manager: Any,
	collection: str,
	session_id: str,
	hard_limit: Optional[int] = None,
	apply: bool = True,
) -> str:
	"""Promociona a v3 un hub legacy cuyo `content` YA cumple el tope duro.

	No re-sintetiza ni toca el texto: deriva `hub_title`/`hub_terms` y actualiza
	los contadores. Es la salida para hubs viejos compactos que el LLM no logra
	re-sintetizar por debajo de 1.000 (se quedarían en bucle). Devuelve
	`promoted|already|over_hard|missing`.
	"""
	from red_pill.memento.hub_terms import hub_terms_chars, select_hub_terms

	hid = hub_point_id(collection, session_id)
	try:
		points = memory_manager.client.retrieve(collection_name=collection, ids=[hid], with_payload=True)
	except Exception:
		return "missing"
	if not points:
		return "missing"
	payload = points[0].payload or {}
	if int(payload.get("hub_synth_version") or 0) >= HUB_SYNTH_VERSION:
		return "already"
	content = str(payload.get("content") or "")
	title = str(payload.get("hub_title") or "").strip()
	if not title:
		first = content.split("\n", 1)[0].strip()
		title = first if len(first) <= 120 else ""
	limit = int(hard_limit or getattr(cfg, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000) or 1000)
	summary_chars = len(content) - (len(title) + 1 if title and content.startswith(title + "\n") else 0)
	if summary_chars > limit:
		return "over_hard"
	members = _load_session_members(memory_manager, collection, session_id)
	terms = select_hub_terms(content, title=title)
	if not apply:
		return "would_promote"
	updates: Dict[str, Any] = {
		"hub_synth_version": HUB_SYNTH_VERSION,
		"hub_title": title,
		"hub_terms": terms,
		"hub_terms_chars": hub_terms_chars(terms),
		"hub_members_count": len(members),
		"hub_migration_blocked": False,
		"hub_migration_blocked_reason": "",
		"hub_members_checked_at": time.time(),
		"hub_promoted_mechanical": True,
	}
	try:
		memory_manager.client.set_payload(collection_name=collection, payload=updates, points=[hid])
	except Exception as exc:
		logger.warning(f"[HUBS] no se pudo promocionar {collection}:{session_id}: {exc}")
		return "missing"
	_mark_members(memory_manager, collection, members, hid)
	return "promoted"


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


def _hub_backup_dir() -> Path:
	from red_pill.core.paths import get_state_dir

	return Path(get_state_dir()) / "backups" / f"hub_payloads_{time.strftime('%Y%m%d')}"


def _safe_backup_name(text: str) -> str:
	return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:120]


def backup_hub_payload(
	memory_manager: Any,
	collection: str,
	session_id: str,
	backup_dir: Optional[str] = None,
) -> Optional[str]:
	"""Guarda el hub y el estado `hubbed/hub_id` de sus miembros ANTES de migrar.

	Devuelve la ruta del JSON o None si el hub no existe. Es la red de seguridad
	de D-11: `restore_hub_payload` revierte payload, vector y marcas de miembros.
	"""
	hid = hub_point_id(collection, session_id)
	try:
		points = memory_manager.client.retrieve(collection_name=collection, ids=[hid], with_payload=True, with_vectors=True)
	except Exception as exc:
		logger.warning(f"[HUBS] backup: no se pudo leer {collection}:{session_id}: {exc}")
		return None
	if not points:
		return None
	rec = points[0]
	vector = rec.vector if not isinstance(rec.vector, dict) else next(iter(rec.vector.values()), None)
	members = load_session_members(memory_manager, collection, session_id)
	data = {
		"collection": collection,
		"session_id": session_id,
		"point_id": hid,
		"vector": vector,
		"payload": rec.payload or {},
		"members": [
			{"id": str(pid), "hubbed": bool((pl or {}).get("hubbed")), "hub_id": (pl or {}).get("hub_id")} for pid, pl in members
		],
		"backed_up_at": time.time(),
	}
	out_dir = Path(backup_dir) if backup_dir else _hub_backup_dir()
	out_dir.mkdir(parents=True, exist_ok=True)
	path = out_dir / f"{_safe_backup_name(collection)}__{_safe_backup_name(session_id)}.json"
	path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
	logger.info(f"[HUBS] backup escrito: {path}")
	return str(path)


def restore_hub_payload(memory_manager: Any, backup_path: str) -> bool:
	"""Revierte un hub desde el JSON de `backup_hub_payload` (payload+vector+marcas)."""
	from qdrant_client.http import models as qm

	data = json.loads(Path(backup_path).read_text(encoding="utf-8"))
	collection = str(data["collection"])
	point_id = str(data["point_id"])
	payload = data.get("payload") or {}
	vector = data.get("vector")
	if vector is None:
		raise ValueError(f"backup sin vector: {backup_path}")
	memory_manager.client.upsert(
		collection_name=collection,
		points=[qm.PointStruct(id=point_id, vector=vector, payload=payload)],
	)
	members = data.get("members") or []
	unmark = [m["id"] for m in members if not m.get("hubbed")]
	if unmark:
		memory_manager.client.delete_payload(collection_name=collection, keys=["hubbed", "hub_id"], points=unmark)
	for member in members:
		if member.get("hubbed"):
			memory_manager.client.set_payload(
				collection_name=collection,
				payload={"hubbed": True, "hub_id": member.get("hub_id")},
				points=[member["id"]],
			)
	logger.info(f"[HUBS] restore aplicado: {backup_path}")
	return True
