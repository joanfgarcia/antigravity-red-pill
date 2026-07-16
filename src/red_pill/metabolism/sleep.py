"""
Lazarus Sleep Engine — Memory Consolidation Pipeline
=====================================================
Biological sleep cycle for the Red Pill ecosystem. Processes raw interaction
buffers (Qdrant + filesystem staging) through distillation, fixation, hub
synthesis, thread weaving, erosion and identity evolution.

Architecture Decision Record (ADR-SLEEP-001) — 2026-05-31
----------------------------------------------------------
STATUS: Deferred.

This module is a known God Class (~940 LOC, 12 top-level symbols). A
decomposition into a pipeline orchestrator + phase plugins was analyzed
and *intentionally deferred* for the following reasons:

1. The module works reliably in autonomous nightly cycles (AWAKENINGs).
2. The macro phases (preflight → drain → staging → gamma → delta →
	evolution → cleanup) are sequential and could be pipeline stages.
	However, the drain loop's micro-level (chunk → distill → fixate →
	link → hub) has tightly coupled mutable state that resists clean
	plugin boundaries.
3. The file is rarely modified — the cost/risk of reorganization does
	not justify the marginal readability gain today.

TRIGGER TO REVISIT: If the file exceeds ~1200 LOC, or if new phases
need to be added to the cycle, revisit decomposition into:

	metabolism/
	├── sleep.py              → Orchestrator (SleepPipeline + SleepContext)
	├── phases/preflight.py   → VRAM check, signal gating
	├── phases/drain.py       → Core drain loop (uses chunker, distiller)
	├── phases/staging.py     → Filesystem cascade ingestion
	├── phases/gamma.py       → Session anchor distillation
	├── phases/delta.py       → Bayesian hub erosion
	├── chunker.py            → chunk_text, _sanitize_llm_json
	├── distiller.py          → distill_engram, synthesize_hub
	├── categorizer.py        → detect_category_heuristics
	├── ephemeral_server.py   → EphemeralServer + _check_llm_available
	└── thread_weaver.py      → Thread state persistence + linking

See: https://github.com/joanfgarcia/antigravity-red-pill/pull/62
"""

import json
import logging
import os
import time

from qdrant_client.models import Filter

import red_pill.config as cfg
from red_pill.core.paths import get_staging_dir
from red_pill.core.vram_probe import VramProbe
from red_pill.events import SleepCompletedEvent, get_event_bus
from red_pill.metabolism.categorizer import detect_category_heuristics
from red_pill.metabolism.chunker import chunk_text
from red_pill.metabolism.distiller import distill_engram, distill_session_anchors, synthesize_hub
from red_pill.metabolism.ephemeral_server import EphemeralServer, _check_llm_available
from red_pill.metabolism.evolution import IdentityEvaluator
from red_pill.metabolism.thread_weaver import _load_thread_state, _save_thread_state

logger = logging.getLogger(__name__)

# ── Thread Weaving state ──────────────────────────────────────────────────────


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

	# Retrieve all synthesis hubs in work_memories
	scroll_filter = qm.Filter(must=[qm.FieldCondition(key="metadata.lazarus_phase", match=qm.MatchValue(value="synthesis_hub"))])

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

			# Deletion threshold: if score <= 0.3 or intensity <= 0.05
			deletion_threshold = 0.3
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


def perform_sleep_cycle(memory_manager, mode: str = "lazy") -> int:
	"""
	Lazarus Phase 2, 3 & 4: Consolidation, Fixation, and Synaptic Dreaming.
	v6.6.0: Now including Phase Gamma Logical Distillation.
	"""
	logger.info("=== LAZARUS PULSE: Initiating Synaptic Dreaming (NREM/REM) ===")

	client = memory_manager.client
	collection = "interaction_memories"
	new_work_hubs = []

	if not client.collection_exists(collection):
		logger.warning("Sleep cycle aborted: fast buffer does not exist.")
		return 0

	# --- Protocol 770: Cryo-Preservation Logic ---
	active_signals = []
	try:
		sig_result = memory_manager.client.scroll(collection_name="signal_memories", limit=100)
		active_signals = [s.payload.get("name") for s in sig_result[0] if s.payload]
	except Exception:
		pass

	hibernating = "korsakoff_amnesia" in active_signals
	thermal_stress = "cpu_fever" in active_signals or "cuda_cortex_failure" in active_signals

	if hibernating:
		logger.info("[SLEEP ENGINE] Korsakoff active (Operator absent). Switching to PRESERVATION MODE (Culling disabled).")
	if thermal_stress:
		logger.warning("[SLEEP ENGINE] System stress detected. Minimizing metabolic load.")

	# ── VRAM Preflight Check ──────────────────────────────────────────────
	# Query free VRAM right now — before attempting to load the LLM. If the
	# GPU is already occupied (game, other model, IDE inference), abort this
	# cycle gracefully rather than fighting for VRAM mid-distillation.
	# Skip this check if the LLM is already online (resident model on GPU).
	_vram_backend = VramProbe.get_backend()
	if _vram_backend != "cpu" and not _check_llm_available():
		_free_vram_mb = VramProbe.get_free_mb()
		_min_free_mb = cfg.SLEEP_MIN_FREE_VRAM_MB
		if _free_vram_mb < _min_free_mb:
			logger.warning(f"[SLEEP ENGINE] VRAM preflight failed: {_free_vram_mb} MB free, {_min_free_mb} MB required. Aborting sleep cycle.")
			try:
				# Deferred, not failed: the GPU is committed (training) so consolidation
				# waits its turn. A "status" signal does NOT escalate (only "pain" does,
				# see MemoryManager.inject_signal) and stays visible on the dashboard as a
				# benign alert; the successful next cycle auto-clears it (~line 1318).
				memory_manager.inject_signal(
					"vram_busy",
					intensity=3.0,
					signal_type="status",
					muted=False,
					source="SLEEP_ENGINE",
				)
			except Exception as _e:
				logger.debug(f"[SLEEP ENGINE] vram_busy signal failed: {_e}")
			return 0
		logger.debug(f"[SLEEP ENGINE] VRAM preflight OK: {_free_vram_mb} MB free ({_vram_backend}).")

	# LLM Health Check & Ephemeral Server
	ephemeral_server = EphemeralServer()
	if not _check_llm_available():
		logger.warning("[SLEEP ENGINE] Local LLM is offline. Launching Ephemeral Samantha Server...")
		try:
			if not ephemeral_server.start(memory_manager):
				return 0
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to start Ephemeral Server: {e}")
			return 0

	# ── Drain Loop ────────────────────────────────────────────────────────
	total_processed = 0
	batch_number = 0
	max_batches = getattr(cfg, "SLEEP_MAX_BATCHES", 1000)
	consecutive_llm_failures = 0
	scroll_limit = cfg.SLEEP_SCROLL_LIMIT
	max_llm_failures = cfg.SLEEP_MAX_LLM_FAILURES
	# Raw points that never get deleted (write failures / LLM-failed with 0 chunks) would be
	# re-scrolled from the top every batch and re-distilled into NEW parents (duplicates),
	# spinning up to max_batches. Track them and exclude them from subsequent scrolls.
	failed_ids: set = set()

	while True:
		batch_number += 1
		if batch_number > max_batches:
			logger.warning(f"[SLEEP ENGINE] Safety limit reached ({max_batches} batches). Forcing exit to protect hardware.")
			break

		if consecutive_llm_failures >= max_llm_failures:
			logger.error("[SLEEP ENGINE] Thermal breaker tripped. Aborting drain loop.")
			break

		if batch_number > 1 and not _check_llm_available():
			break

		try:
			from qdrant_client import models as _qm

			scroll_filter = Filter(must_not=[_qm.HasIdCondition(has_id=list(failed_ids))]) if failed_ids else Filter()
			scroll_result, _ = client.scroll(collection_name=collection, scroll_filter=scroll_filter, limit=scroll_limit, with_payload=True)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to fetch raw buffer: {e}")
			break

		if not scroll_result:
			break

		batch_processed = 0
		for point in scroll_result:
			raw_id = point.id
			payload = point.payload or {}
			raw_text = payload.get("content", "")
			if not raw_text and "prompt" in payload and "response" in payload:
				raw_text = f"USER: {payload['prompt']}\n\nASSISTANT: {payload['response']}"
			if not raw_text:
				continue

			# Refactoring chunks
			chunks = []
			if raw_text.startswith("USER: ") and "\n\nASSISTANT: " in raw_text:
				parts = raw_text.split("\n\nASSISTANT: ", 1)
				p_text = parts[0].replace("USER: ", "", 1).strip()
				r_text = parts[1].strip()
				if p_text:
					chunks.extend([f"Operator Prompt: {c}" for c in chunk_text(p_text)])
				if r_text:
					chunks.extend([f"AI Response Node: {c}" for c in chunk_text(r_text)])
			else:
				chunks = chunk_text(raw_text)

			import uuid

			parent_id = str(uuid.uuid4())
			child_ids = []

			surviving_chunks = []
			prev_chunk_id = None
			chunks_saved = 0

			# Target collection heuristics
			raw_metadata = (point.payload or {}).get("metadata", {})
			model_name = raw_metadata.get("model", "unknown") if isinstance(raw_metadata, dict) else "unknown"
			llm_category = raw_metadata.get("category", "") if isinstance(raw_metadata, dict) else ""
			if llm_category in ("work", "social"):
				fallback_cat = llm_category
			else:
				fallback_cat = detect_category_heuristics(raw_text)

			# Consistent collection to prevent link fragmentation and hub overwriting
			target_col = f"{fallback_cat}_memories"

			point_write_failed = False
			point_llm_failed = False
			for i, chunk in enumerate(chunks):
				distilled = distill_engram(chunk, fallback_category=fallback_cat)
				summary = distilled.get("summary", "")
				if distilled.get("_is_fallback"):
					consecutive_llm_failures += 1
					point_llm_failed = True
					continue
				consecutive_llm_failures = 0

				current_threshold = 0.0 if hibernating else cfg.SLEEP_CULL_THRESHOLD
				if distilled.get("emotion") == "neutral" and distilled.get("intensity", 0.5) < current_threshold:
					continue

				surviving_chunks.append(distilled)

				# Dynamic chunk-level routing
				chunk_cat = distilled.get("category")
				if chunk_cat not in ("work", "social"):
					chunk_col = target_col
				else:
					chunk_col = f"{chunk_cat}_memories"

				try:
					new_id = memory_manager.add_memory(
						collection=chunk_col,
						text=summary,
						metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id, "model": model_name, "parent_id": parent_id},
						color="blue" if chunk_col == "work_memories" else "purple",
						emotion=distilled.get("emotion", "neutral"),
						intensity=distilled.get("intensity", 0.5),
					)
					if prev_chunk_id and new_id:
						client.set_payload(collection_name=chunk_col, payload={"associations": [prev_chunk_id]}, points=[new_id])
					if new_id:
						prev_chunk_id = new_id
						child_ids.append(new_id)
						batch_processed += 1
						chunks_saved += 1
				except Exception as e:
					logger.error(f"[SLEEP ENGINE] Metabolic Fixation failed for {raw_id}: {e}")
					point_write_failed = True

			# Hub Synthesis
			if len(surviving_chunks) > 1 and prev_chunk_id and not point_write_failed:
				hub_summary = synthesize_hub([c["summary"] for c in surviving_chunks])
				try:
					hub_id = memory_manager.add_memory(
						collection=target_col,
						text=hub_summary,
						metadata={
							"lazarus_phase": "synthesis_hub",
							"node_type": "synthesis_hub",
							"source_buffer_id": raw_id,
							"model": model_name,
							"parent_id": parent_id,
						},
						color="cyan",
						emotion=surviving_chunks[-1]["emotion"],
						intensity=max([c["intensity"] for c in surviving_chunks]),
					)
					if hub_id:
						client.set_payload(collection_name=target_col, payload={"associations": [prev_chunk_id]}, points=[hub_id])
						child_ids.append(hub_id)
						batch_processed += 1
						chunks_saved += 1
						if target_col == "work_memories":
							new_work_hubs.append(hub_summary)

						# Thread Weaving
						thread_state = _load_thread_state()
						prev_hub_id = thread_state.get(target_col)
						if prev_hub_id:
							client.set_payload(collection_name=target_col, payload={"prev_session_hub": prev_hub_id}, points=[hub_id])
							client.set_payload(collection_name=target_col, payload={"next_session_hub": str(hub_id)}, points=[prev_hub_id])
						thread_state[target_col] = str(hub_id)
						_save_thread_state(thread_state)
				except Exception:
					pass

			# Save raw_parent verbatim engram
			if chunks_saved > 0 and not point_write_failed:
				try:
					parent_metadata = {
						"lazarus_phase": "raw_parent",
						"source_buffer_id": raw_id,
						"model": model_name,
						"associations": child_ids,
						"immune": True,
					}

					# Ariadne's Thread for raw parents
					thread_state = _load_thread_state()
					prev_parent_key = f"last_raw_parent_{target_col}"
					prev_parent_id = thread_state.get(prev_parent_key)
					if prev_parent_id:
						parent_metadata["prev_raw_parent"] = prev_parent_id

					parent_id_written = memory_manager.add_memory(
						collection=target_col,
						text=raw_text,
						metadata=parent_metadata,
						point_id=parent_id,
						force_immune=True,
					)

					if parent_id_written and prev_parent_id:
						client.set_payload(collection_name=target_col, payload={"next_raw_parent": parent_id_written}, points=[prev_parent_id])

					if parent_id_written:
						thread_state[prev_parent_key] = parent_id_written
						_save_thread_state(thread_state)

					client.delete(collection_name=collection, points_selector=[raw_id])
				except Exception as e:
					logger.error(f"[SLEEP ENGINE] Failed to save raw parent engram: {e}")
					point_write_failed = True
			elif not point_llm_failed and not point_write_failed:
				client.delete(collection_name=collection, points_selector=[raw_id])

			# Any raw point NOT deleted this pass would be re-scrolled and re-distilled into a
			# fresh parent next batch — record it so the scroll filter skips it (no duplicates).
			if point_write_failed or point_llm_failed:
				failed_ids.add(raw_id)

		total_processed += batch_processed

	# ── Staging Buffer Processing (Productor-Consumidor Fallback) ─────────
	STAGING_DIR = str(get_staging_dir())
	if os.path.exists(STAGING_DIR):
		logger.info(f"[SLEEP ENGINE] Sweeping Staging Buffer: {STAGING_DIR}")
		try:
			for filename in os.listdir(STAGING_DIR):
				if not filename.endswith(".json"):
					continue
				filepath = os.path.join(STAGING_DIR, filename)
				try:
					with open(filepath, "r") as f:
						payload = json.load(f)
				except Exception as e:
					logger.error(f"[SLEEP ENGINE] Unreadable file {filename}: {e}")
					continue

				raw_id = payload.get("id", filename.replace(".json", ""))
				model_name = payload.get("model") or payload.get("summary", {}).get("model") or "unknown"
				staging_workspace = payload.get("workspace")
				ws_meta = {"workspace": staging_workspace} if staging_workspace else {}
				raw_text = ""
				for step in payload.get("steps", []):
					txt = step.get("message", {}).get("text", "")
					if txt:
						intent_str = str(step.get("intent", ""))
						intent_role = "ASSISTANT" if "ASSISTANT" in intent_str else "USER"
						raw_text += f"{intent_role}: {txt}\n\n"

				if not raw_text.strip():
					os.remove(filepath)
					continue

				import uuid

				parent_id = str(uuid.uuid4())
				child_ids = []

				chunks = chunk_text(raw_text)
				surviving_chunks = []
				prev_chunk_id = None

				for chunk in chunks:
					distilled = distill_engram(chunk, fallback_category="work")
					summary = distilled.get("summary", "")
					if distilled.get("_is_fallback"):
						continue  # LLM failed to distill

					current_threshold = 0.0 if hibernating else cfg.SLEEP_CULL_THRESHOLD
					if distilled.get("emotion") == "neutral" and distilled.get("intensity", 0.5) < current_threshold:
						continue

					surviving_chunks.append(distilled)

					# Dynamic category routing for staging chunks
					chunk_cat = distilled.get("category")
					if chunk_cat not in ("work", "social"):
						chunk_col = "work_memories"
					else:
						chunk_col = f"{chunk_cat}_memories"

					try:
						new_id = memory_manager.add_memory(
							collection=chunk_col,
							text=summary,
							metadata={
								"lazarus_phase": "sequence_chunk",
								"source_buffer_id": raw_id,
								"model": model_name,
								"parent_id": parent_id,
								**ws_meta,
							},
							color="blue" if chunk_col == "work_memories" else "purple",
							emotion=distilled.get("emotion", "neutral"),
							intensity=distilled.get("intensity", 0.5),
						)
						if prev_chunk_id and new_id:
							client.set_payload(collection_name=chunk_col, payload={"associations": [prev_chunk_id]}, points=[new_id])
						if new_id:
							prev_chunk_id = new_id
							child_ids.append(new_id)
							total_processed += 1
					except Exception:
						pass

				# Hub Synthesis
				if len(surviving_chunks) > 1 and prev_chunk_id:
					hub_summary = synthesize_hub([c["summary"] for c in surviving_chunks])
					try:
						hub_id = memory_manager.add_memory(
							collection="work_memories",
							text=hub_summary,
							metadata={
								"lazarus_phase": "synthesis_hub",
								"node_type": "synthesis_hub",
								"source_buffer_id": raw_id,
								"model": model_name,
								"parent_id": parent_id,
								**ws_meta,
							},
							color="cyan",
							emotion=surviving_chunks[-1]["emotion"],
							intensity=max([c["intensity"] for c in surviving_chunks]),
						)
						if hub_id:
							client.set_payload(collection_name="work_memories", payload={"associations": [prev_chunk_id]}, points=[hub_id])
							child_ids.append(hub_id)
							new_work_hubs.append(hub_summary)

							# Thread Weaving
							thread_state = _load_thread_state()
							prev_hub_id = thread_state.get("work_memories")
							if prev_hub_id:
								client.set_payload(collection_name="work_memories", payload={"prev_session_hub": prev_hub_id}, points=[hub_id])
								client.set_payload(collection_name="work_memories", payload={"next_session_hub": str(hub_id)}, points=[prev_hub_id])
							thread_state["work_memories"] = str(hub_id)
							_save_thread_state(thread_state)
					except Exception:
						pass

				# Save raw_parent verbatim engram for staging file
				if len(child_ids) > 0:
					try:
						parent_metadata = {
							"lazarus_phase": "raw_parent",
							"source_buffer_id": raw_id,
							"model": model_name,
							"associations": child_ids,
							"immune": True,
							**ws_meta,
						}

						# Ariadne's Thread for raw parents in work_memories
						thread_state = _load_thread_state()
						prev_parent_key = "last_raw_parent_work_memories"
						prev_parent_id = thread_state.get(prev_parent_key)
						if prev_parent_id:
							parent_metadata["prev_raw_parent"] = prev_parent_id

						parent_id_written = memory_manager.add_memory(
							collection="work_memories",
							text=raw_text,
							metadata=parent_metadata,
							point_id=parent_id,
							force_immune=True,
						)

						if parent_id_written and prev_parent_id:
							client.set_payload(
								collection_name="work_memories", payload={"next_raw_parent": parent_id_written}, points=[prev_parent_id]
							)

						if parent_id_written:
							thread_state[prev_parent_key] = parent_id_written
							_save_thread_state(thread_state)
					except Exception as e:
						logger.error(f"[SLEEP ENGINE] Failed to save raw parent engram for staging file: {e}")

				# Purge document
				logger.info(f"[SLEEP ENGINE] Ingested cascade {raw_id}. Purging staging file.")
				os.remove(filepath)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Staging loop failed: {e}")

	# PHASE GAMMA: Logical Distillation (The Session Anchor)
	if new_work_hubs:
		distill_session_anchors(memory_manager, new_work_hubs)

	# Phase Delta: Hub Bayesian Erosion
	try:
		erode_work_hubs(memory_manager)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to run Bayesian hub erosion: {e}")

	# RhizoDB Washout and Structural Pruning
	try:
		run_rhizodb_washout_and_pruning(memory_manager)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to run RhizoDB washout and pruning: {e}")

	try:
		IdentityEvaluator.evaluate_set_point(memory_manager)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Personality evolution failed: {e}")

	logger.info(f"=== LAZARUS PULSE: Sleep Cycle complete. {total_processed} engrams synaptically woven. ===")
	try:
		from red_pill.core.notifier import SovereignNotifier

		SovereignNotifier.clear_bunker_signal(memory_manager, "local_llm_offline")
		SovereignNotifier.clear_bunker_signal(memory_manager, "ariadne_thread_running")
		# Auto-evaporate any pending vram_busy signal: the cycle completed successfully,
		# meaning the GPU had enough headroom. Clear the alert so the Córtex stays clean.
		SovereignNotifier.clear_bunker_signal(memory_manager, "vram_busy")
	except Exception:
		pass

	ephemeral_server.stop(memory_manager, total_processed)

	get_event_bus().emit(SleepCompletedEvent(collection=collection, processed_count=total_processed, mode=mode))
	return total_processed
