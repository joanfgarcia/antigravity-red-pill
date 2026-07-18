"""Cross-collection synaptic axons (ADR-AXON-001): weave, repair, prune.

CPU-only sleep-phase logic. Candidates come from Qdrant server-side search with
a temporal range filter (same pattern as dream()); no manual cosine loops.
Bidirectional writes are two set_payload calls and thus not atomic — the repair
pass makes the weave self-healing instead of transactional: a one-way link
created by a mid-write failure is completed on the next cycle.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import models

import red_pill.config as cfg
from red_pill.core.paths import get_state_dir
from red_pill.schemas import Axon, normalize_associations

logger = logging.getLogger(__name__)

CROSS_TYPE = "temporal_semantic"
SOURCE_COLLECTION = "social_memories"  # smaller collection sweeps the bigger one
TARGET_COLLECTION = "work_memories"

# Structural material never carries axons: mirrors search_and_reinforce exclusions.
_STRUCTURAL_EXCLUSIONS = [
	models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent")),
	models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="sequence_chunk")),
	models.FieldCondition(key="_is_fragment", match=models.MatchValue(value=True)),
]


def _axon_state_path():
	return get_state_dir() / "axon_weaver_state.json"


def load_axon_state() -> dict:
	try:
		path = _axon_state_path()
		if path.exists():
			with open(path) as f:
				return dict(json.load(f))
	except Exception:
		pass
	return {"completed_runs": 0}


def save_axon_state(state: dict) -> None:
	try:
		path = _axon_state_path()
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "w") as f:
			json.dump(state, f)
	except Exception as e:
		logger.warning(f"[AXON WEAVER] Could not persist state: {e}")


def compute_axon_weight(similarity: float, delta_seconds: float) -> float:
	"""W = α·sim + (1-α)·(1 - Δt/Δt_max). Callers gate on cfg.AXON_GATE."""
	dt_max = cfg.AXON_DT_MAX_HOURS * 3600.0
	temporal = max(0.0, 1.0 - (abs(delta_seconds) / dt_max)) if dt_max > 0 else 0.0
	return round(cfg.AXON_ALPHA * similarity + (1.0 - cfg.AXON_ALPHA) * temporal, 4)


def _split_associations(payload: dict, own_collection: str) -> Tuple[List[Any], List[Axon]]:
	"""Return (raw local entries kept as-is, cross axons parsed)."""
	raw = payload.get("associations", []) if payload else []
	if not isinstance(raw, list):
		raw = []
	local_raw: List[Any] = []
	cross: List[Axon] = []
	for entry in raw:
		parsed = normalize_associations([entry])
		if parsed and parsed[0].is_cross(own_collection):
			cross.append(parsed[0])
		else:
			# local links (and unparseable entries) stay untouched — conservative
			local_raw.append(entry)
	return local_raw, cross


def _prune_cross(cross: List[Axon], cap: int) -> Tuple[List[Axon], int]:
	"""Deferred soft-cap pruning: keep the heaviest links. Legacy/local links
	never compete with cross axons for this budget (Joan's Q1 decision)."""
	if len(cross) <= cap:
		return cross, 0
	kept = sorted(cross, key=lambda a: a.weight, reverse=True)[:cap]
	return kept, len(cross) - cap


def _write_associations(client, collection: str, point_id: str, local_raw: List[Any], cross: List[Axon]) -> None:
	serialized = list(local_raw) + [a.to_payload() for a in cross]
	client.set_payload(collection_name=collection, payload={"associations": serialized}, points=[point_id])


def _append_axon(
	client,
	collection: str,
	point_id: str,
	payload: Optional[dict],
	new_axon: Axon,
	stats: Dict[str, Any],
) -> bool:
	"""Idempotent append with hard-ceiling guard (2×cap). Returns True if written."""
	local_raw, cross = _split_associations(payload or {}, collection)
	if any(a.id == new_axon.id for a in cross):
		return False
	if len(cross) >= 2 * cfg.AXON_MAX_CROSS:
		stats["hard_ceiling_hits"] += 1
		logger.warning(f"[AXON WEAVER] {collection}:{point_id} at hard axon ceiling ({len(cross)}) — insert skipped.")
		return False
	cross.append(new_axon)
	_write_associations(client, collection, point_id, local_raw, cross)
	return True


def weave_cross_axons(memory_manager) -> Dict[str, Any]:
	"""One weaving cycle over the recent window: weave → repair → prune."""
	client = memory_manager.client
	now = time.time()
	window_start = now - cfg.AXON_WINDOW_HOURS * 3600.0
	dt_max_s = cfg.AXON_DT_MAX_HOURS * 3600.0

	stats: Dict[str, Any] = {
		"candidates_evaluated": 0,
		"axons_woven": 0,
		"axons_repaired": 0,
		"axons_pruned": 0,
		"rejected_by_gate": 0,
		"hard_ceiling_hits": 0,
		"weights_accepted": [],
		"weights_rejected": [],
	}

	window_filter = models.Filter(
		must=[models.FieldCondition(key="created_at", range=models.Range(gte=window_start))],
		must_not=list(_STRUCTURAL_EXCLUSIONS),
	)

	# ── Weave ──
	source_points: List[Any] = []
	offset = None
	while True:
		batch, offset = client.scroll(
			collection_name=SOURCE_COLLECTION,
			scroll_filter=window_filter,
			limit=64,
			with_payload=True,
			with_vectors=True,
			offset=offset,
		)
		source_points.extend(batch)
		if offset is None:
			break

	touched: Dict[Tuple[str, str], None] = {}
	for point in source_points:
		payload = point.payload or {}
		created_at = float(payload.get("created_at", 0.0) or 0.0)
		if point.vector is None or not created_at:
			continue
		try:
			candidates = client.query_points(
				collection_name=TARGET_COLLECTION,
				query=list(point.vector),
				query_filter=models.Filter(
					must=[models.FieldCondition(key="created_at", range=models.Range(gte=created_at - dt_max_s, lte=created_at + dt_max_s))],
					must_not=list(_STRUCTURAL_EXCLUSIONS),
				),
				limit=8,
				with_payload=True,
				with_vectors=False,
			).points
		except Exception as e:
			logger.debug(f"[AXON WEAVER] candidate query failed for {point.id}: {e}")
			continue

		for hit in candidates:
			hit_payload = hit.payload or {}
			hit_created = float(hit_payload.get("created_at", 0.0) or 0.0)
			if not hit_created:
				continue
			stats["candidates_evaluated"] += 1
			weight = compute_axon_weight(float(hit.score), hit_created - created_at)
			if weight < cfg.AXON_GATE:
				stats["rejected_by_gate"] += 1
				stats["weights_rejected"].append(weight)
				continue
			stats["weights_accepted"].append(weight)
			wrote_a = _append_axon(
				client,
				SOURCE_COLLECTION,
				str(point.id),
				payload,
				Axon(id=str(hit.id), target_collection=TARGET_COLLECTION, weight=weight, association_type=CROSS_TYPE),
				stats,
			)
			if wrote_a:
				# keep the in-memory payload in sync for subsequent candidates of the same source
				payload.setdefault("associations", []).append(
					{"id": str(hit.id), "target_collection": TARGET_COLLECTION, "weight": weight, "association_type": CROSS_TYPE}
				)
				_append_axon(
					client,
					TARGET_COLLECTION,
					str(hit.id),
					hit_payload,
					Axon(id=str(point.id), target_collection=SOURCE_COLLECTION, weight=weight, association_type=CROSS_TYPE),
					stats,
				)
				stats["axons_woven"] += 1
				touched[(SOURCE_COLLECTION, str(point.id))] = None
				touched[(TARGET_COLLECTION, str(hit.id))] = None

	# ── Repair (symmetry self-healing over the window) ──
	stats["axons_repaired"] = _repair_symmetry(client, window_filter, stats)

	# ── Deferred prune (soft cap with full-cycle information) ──
	for collection, point_id in list(touched.keys()):
		try:
			records = client.retrieve(collection_name=collection, ids=[point_id], with_payload=True, with_vectors=False)
			if not records:
				continue
			local_raw, cross = _split_associations(records[0].payload or {}, collection)
			kept, pruned = _prune_cross(cross, cfg.AXON_MAX_CROSS)
			if pruned:
				_write_associations(client, collection, point_id, local_raw, kept)
				stats["axons_pruned"] += pruned
		except Exception as e:
			logger.debug(f"[AXON WEAVER] prune failed for {collection}:{point_id}: {e}")

	return stats


def _repair_symmetry(client, window_filter, stats: Dict[str, Any]) -> int:
	"""Ensure every cross axon in the window has its reciprocal; drop dangling ones."""
	repaired = 0
	for collection, opposite in ((SOURCE_COLLECTION, TARGET_COLLECTION), (TARGET_COLLECTION, SOURCE_COLLECTION)):
		offset = None
		while True:
			try:
				batch, offset = client.scroll(
					collection_name=collection,
					scroll_filter=window_filter,
					limit=64,
					with_payload=True,
					with_vectors=False,
					offset=offset,
				)
			except Exception:
				break
			for point in batch:
				local_raw, cross = _split_associations(point.payload or {}, collection)
				cross_to_opposite = [a for a in cross if a.target_collection == opposite]
				if not cross_to_opposite:
					continue
				try:
					targets = client.retrieve(collection_name=opposite, ids=[a.id for a in cross_to_opposite], with_payload=True, with_vectors=False)
				except Exception:
					continue
				targets_by_id = {str(t.id): t for t in targets}
				surviving = [a for a in cross if a.target_collection != opposite]
				dropped = 0
				for axon in cross_to_opposite:
					target = targets_by_id.get(axon.id)
					if target is None:
						dropped += 1  # dangling: target eroded away — GC (P5)
						continue
					surviving.append(axon)
					_, target_cross = _split_associations(target.payload or {}, opposite)
					if not any(t.id == str(point.id) for t in target_cross):
						if _append_axon(
							client,
							opposite,
							axon.id,
							target.payload,
							Axon(id=str(point.id), target_collection=collection, weight=axon.weight, association_type=axon.association_type),
							stats,
						):
							repaired += 1
				if dropped:
					_write_associations(client, collection, str(point.id), local_raw, surviving)
					stats["axons_pruned"] += dropped
			if offset is None:
				break
	return repaired
