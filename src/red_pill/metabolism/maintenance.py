"""Memory maintenance: Bayesian work-hub erosion and RhizoDB washout/pruning.

Extracted from sleep.py per ADR-SLEEP-001. CPU-only housekeeping — no LLM, no GPU
(so the sleep orchestrator can run these even while the GPU is committed to training).
"""

import logging
import time

import red_pill.config as cfg

logger = logging.getLogger(__name__)


def erode_work_hubs(memory_manager) -> None:
	"""
	Applies Bayesian erosion to old/unreferenced synthesis hubs in work_memories.
	Hubs that haven't been recalled/referenced in the last cycle have their
	utility_beta increased (reducing utility score) and their intensity decayed.
	"""
	client = memory_manager.client
	collection = "work_memories"
	if not client.collection_exists(collection):
		return

	from qdrant_client import models as qm

	# Retrieve all synthesis hubs in work_memories. lazarus_phase lives at the
	# payload top level (add_memory flattens metadata) — the old nested
	# "metadata.lazarus_phase" key matched 0 points, so erosion never ran.
	scroll_filter = qm.Filter(must=[qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value="synthesis_hub"))])

	try:
		# Scroll to get all hubs (limit=1000 should be plenty for hubs)
		scroll_res = client.scroll(collection_name=collection, scroll_filter=scroll_filter, limit=1000, with_payload=True)
		if isinstance(scroll_res, tuple) and len(scroll_res) == 2:
			hubs = scroll_res[0]
		else:
			hubs = scroll_res if isinstance(scroll_res, list) else []
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to fetch hubs for erosion: {e}")
		return

	if not hubs or not isinstance(hubs, list):
		return

	now = time.time()
	update_operations = []
	points_to_delete = []

	# Cycle duration threshold: 1 cycle is approx 12 hours.
	threshold_seconds = 12 * 3600

	for hub in hubs:
		payload = hub.payload or {}
		if payload.get("immune"):
			continue

		last_recalled = float(payload.get("last_recalled_at", now))

		# If it hasn't been recalled recently
		if now - last_recalled > threshold_seconds:
			alpha = float(payload.get("utility_alpha", 1.0))
			beta = float(payload.get("utility_beta", 1.0))
			intensity = float(payload.get("intensity", 0.5))

			# 1. Bayesian Erosion: Increase uncertainty (beta)
			new_beta = beta + 0.5
			new_utility = alpha / (alpha + new_beta)
			new_score = round(new_utility, 3)

			# 2. Intensity decay: decay intensity by 15% (factor 0.85)
			new_intensity = round(intensity * 0.85, 3)

			# Deletion threshold: single source of truth is the collection's own
			# Bayesian engine, so sleep-side forgetting stays coherent with the
			# read-path lazy decay calibration (must sit below the prior mean 0.5).
			from red_pill.affect import get_memory_engine

			deletion_threshold = getattr(get_memory_engine("bayesian"), "deletion_threshold", 0.2)
			if new_score <= deletion_threshold or new_intensity <= 0.05:
				points_to_delete.append(hub.id)
				logger.info(
					f"[SLEEP ENGINE] Hub {hub.id} in 'work_memories' eroded below threshold (score={new_score}, intensity={new_intensity}). Deleting."
				)
			else:
				update_payload = {"utility_beta": new_beta, "reinforcement_score": new_score, "intensity": new_intensity, "last_recalled_at": now}
				update_operations.append(qm.SetPayloadOperation(set_payload=qm.SetPayload(payload=update_payload, points=[hub.id])))

	if update_operations:
		try:
			client.batch_update_points(collection_name=collection, update_operations=update_operations)
			logger.info(f"[SLEEP ENGINE] Erode hubs: updated {len(update_operations)} hubs in work_memories.")
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to update eroded hubs: {e}")

	if points_to_delete:
		try:
			client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=points_to_delete))
			logger.info(f"[SLEEP ENGINE] Erode hubs: deleted {len(points_to_delete)} hubs in work_memories.")
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to delete eroded hubs: {e}")


def promote_orphan_chunks(memory_manager, collections=("work_memories", "social_memories"), dry_run: bool = False) -> dict:
	"""
	Self-healing pass: a consolidated turn whose chunks have no synthesis_hub
	sibling is invisible to direct recall (sequence_chunk is structurally excluded
	from search, on the premise that "searches go through the hub" — but the hub
	is only synthesized when MORE than one chunk survives). Promote the newest
	chunk of each hub-less parent to synthesis_hub so every turn keeps a
	searchable representative. Multi-chunk parents are additionally flagged
	hub_rebuild_pending=True so a future LLM pass can synthesize a proper hub.

	Doubles as the one-shot legacy migration (first run) and as a per-sleep-cycle
	safety net for any future hub-synthesis failure.
	"""
	client = memory_manager.client
	report: dict = {}

	for collection in collections:
		if not client.collection_exists(collection):
			continue

		chunks_by_parent: dict = {}
		hub_parents = set()
		offset = None
		while True:
			try:
				points, offset = client.scroll(collection_name=collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Orphan-promotion scroll failed in {collection}: {e}")
				break
			for p in points:
				payload = p.payload or {}
				phase = payload.get("lazarus_phase")
				parent = payload.get("parent_id")
				if not parent:
					continue
				if phase == "sequence_chunk":
					chunks_by_parent.setdefault(parent, []).append((float(payload.get("created_at", 0.0)), p.id))
				elif phase == "synthesis_hub":
					hub_parents.add(parent)
			if offset is None:
				break

		promoted = 0
		flagged = 0
		for parent, chunks in chunks_by_parent.items():
			if parent in hub_parents:
				continue
			chunks.sort(key=lambda t: t[0])
			representative = chunks[-1][1]
			new_payload: dict = {"lazarus_phase": "synthesis_hub", "node_type": "synthesis_hub", "promoted_from": "sequence_chunk"}
			if len(chunks) > 1:
				new_payload["hub_rebuild_pending"] = True
				flagged += 1
			if not dry_run:
				try:
					client.set_payload(collection_name=collection, payload=new_payload, points=[representative])
				except Exception as e:
					logger.error(f"[SLEEP ENGINE] Orphan-chunk promotion failed for {representative} in {collection}: {e}")
					continue
			promoted += 1

		report[collection] = {"hubless_parents_promoted": promoted, "multi_chunk_flagged": flagged}
		if promoted:
			logger.info(
				f"[SLEEP ENGINE] Orphan promotion in {collection}: {promoted} hub-less parents got a searchable "
				f"representative ({flagged} pending full hub rebuild){' [dry-run]' if dry_run else ''}."
			)

	return report


def run_rhizodb_washout_and_pruning(memory_manager) -> None:
	"""
	Applies global periodic Washout and Structural Pruning to collections utilizing RhizoDB.
	Washout formula: a_v = gamma * a_v + b(s_v)
	Pruning rule: delete if a_v < 0.1 and s_v < 5.0 (days)
	"""
	client = memory_manager.client
	now = time.time()
	gamma = 0.85
	S_max = 365.0

	# Find collections utilizing rhizodb
	rhizodb_collections = [col for col, eng in cfg.MEMORY_ENGINES.items() if eng == "rhizodb"]

	for collection in rhizodb_collections:
		if not client.collection_exists(collection):
			continue

		from qdrant_client import models as qm

		from red_pill.affect import get_memory_engine

		engine = get_memory_engine("rhizodb")

		try:
			# Scroll to get all points (limit=10000 to cover all social/story memories)
			scroll_res = client.scroll(collection_name=collection, limit=10000, with_payload=True)
			if isinstance(scroll_res, tuple) and len(scroll_res) == 2:
				points = scroll_res[0]
			else:
				points = scroll_res if isinstance(scroll_res, list) else []
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to fetch points for rhizodb processing in {collection}: {e}")
			continue

		if not points:
			continue

		update_operations = []
		points_to_delete = []

		for p in points:
			payload = p.payload or {}
			if payload.get("immune"):
				continue

			# 1. Run lazy decay first to get current activation/score
			decay_updates = engine.calculate_lazy_decay(payload, current_time=now)

			# If lazy decay wants to delete it
			if decay_updates.get("_delete"):
				points_to_delete.append(p.id)
				continue

			score = float(decay_updates.get("reinforcement_score", payload.get("reinforcement_score", 1.0)))
			stability = float(payload.get("stability", 1.0))

			# 2. Apply Washout: a_v = gamma * a_v + b(s_v)
			# b(s_v) = (1 - gamma) * (stability / S_max)
			b_sv = (1.0 - gamma) * (stability / S_max)
			new_score = round(gamma * score + b_sv, 3)

			# 3. Structural Pruning (Poda): delete if a_v < 0.1 and s_v < 5.0
			if new_score < 0.1 and stability < 5.0:
				points_to_delete.append(p.id)
				logger.info(f"[SLEEP ENGINE] Pruning engram {p.id} in {collection}: activation={new_score}, stability={stability}")
			else:
				# Otherwise, update score and commit time
				update_payload = {"reinforcement_score": new_score, "last_recalled_at": now}
				update_operations.append(qm.SetPayloadOperation(set_payload=qm.SetPayload(payload=update_payload, points=[p.id])))

		# Execute updates and deletions
		if update_operations:
			try:
				client.batch_update_points(collection_name=collection, update_operations=update_operations)
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to update washout payloads in {collection}: {e}")

		if points_to_delete:
			try:
				client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=points_to_delete))
				logger.info(f"[SLEEP ENGINE] Deleted {len(points_to_delete)} pruned engrams from {collection}.")
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to delete pruned engrams in {collection}: {e}")


def purge_empty_engrams(memory_manager, collections=("work_memories", "social_memories"), dry_run: bool = False) -> dict:
	"""
	Hygiene pass: engrams whose content is empty/whitespace carry zero recall
	value but real storage and graph cost. Purge them, but FIRST re-stitch the
	raw_parent temporal chain (prev/next_raw_parent) around each victim — the
	one relationship class that does not self-heal (associations and axons
	already tolerate dangling ids via cascade fallback and weaver GC).
	Immune engrams are never purged, only counted (an empty immune anchor is an
	anomaly the operator should see, not one a janitor should resolve).
	"""
	from qdrant_client import models as qm

	client = memory_manager.client
	report: dict = {}

	for collection in collections:
		if not client.collection_exists(collection):
			continue
		victims = []
		skipped_immune = 0
		offset = None
		while True:
			try:
				points, offset = client.scroll(collection_name=collection, limit=512, offset=offset, with_payload=True, with_vectors=False)
			except Exception as e:
				logger.error(f"[HYGIENE] scroll failed in {collection}: {e}")
				break
			for p in points:
				payload = p.payload or {}
				if str(payload.get("content", "")).strip():
					continue
				if payload.get("immune"):
					skipped_immune += 1
					continue
				victims.append((p.id, payload))
			if offset is None:
				break

		restitched = 0
		for victim_id, payload in victims:
			if dry_run:
				continue
			prev_id = payload.get("prev_raw_parent")
			next_id = payload.get("next_raw_parent")
			try:
				if prev_id:
					if next_id:
						client.set_payload(collection_name=collection, payload={"next_raw_parent": str(next_id)}, points=[prev_id])
					else:
						client.delete_payload(collection_name=collection, keys=["next_raw_parent"], points=[prev_id])
					restitched += 1
				if next_id:
					if prev_id:
						client.set_payload(collection_name=collection, payload={"prev_raw_parent": str(prev_id)}, points=[next_id])
					else:
						client.delete_payload(collection_name=collection, keys=["prev_raw_parent"], points=[next_id])
					restitched += 1
			except Exception as e:
				logger.debug(f"[HYGIENE] chain restitch failed around {victim_id}: {e}")
			try:
				client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=[victim_id]))
			except Exception as e:
				logger.error(f"[HYGIENE] delete failed for {victim_id} in {collection}: {e}")

		report[collection] = {"empty_purged": len(victims), "chains_restitched": restitched, "skipped_immune_empty": skipped_immune}
		if victims or skipped_immune:
			logger.info(
				f"[HYGIENE] {collection}: {len(victims)} empty engrams {'found' if dry_run else 'purged'} "
				f"({restitched} chain links restitched, {skipped_immune} immune empties left for the operator)."
			)
	return report
