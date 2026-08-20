"""GPU-heavy consolidation: drain -> staging -> gamma (session anchors).

The tightly-coupled drain loop (chunk -> distill -> fixate -> link -> hub) stays
intact here as ADR-SLEEP-001 requires; only total_processed crosses the phase
boundary. requires_gpu=True, so the runner defers this phase (benign vram_busy
status signal) when the card is committed to training, while the CPU-only
maintenance phases still run.
"""

import json
import logging
import os
import time
from typing import Any

from qdrant_client.models import Filter

import red_pill.config as cfg
from red_pill.core.paths import get_staging_dir
from red_pill.core.vram_probe import VramProbe
from red_pill.metabolism.categorizer import detect_category_heuristics
from red_pill.metabolism.chunker import chunk_text
from red_pill.metabolism.distiller import (
	build_emotional_vector,
	derive_hub_affect,
	distill_engram,
	distill_session_anchors,
	merge_relics,
	synthesize_hub_v2,
)
from red_pill.metabolism.ephemeral_server import EphemeralServer, _check_llm_available
from red_pill.metabolism.phases.base import SleepContext, SleepPhase
from red_pill.metabolism.thread_weaver import _load_thread_state, _save_thread_state

logger = logging.getLogger(__name__)


def reassemble_raw_sequence(client, collection: str, point: Any) -> tuple[str, list[Any]]:
	"""Re-assembles multi-chunk raw fragments sharing parent_id or source_buffer_id
	into a single continuous, un-truncated text before distillation.
	Returns (full_reassembled_text, list_of_all_processed_points)."""
	payload = point.payload or {}
	parent_id = payload.get("parent_id")
	meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
	source_buf_id = payload.get("source_buffer_id") or meta.get("source_buffer_id")
	is_fragment = payload.get("_is_fragment") or (payload.get("total_chunks", 1) > 1)

	if not (is_fragment or parent_id or source_buf_id or payload.get("chunk_index") is not None):
		content = payload.get("content", "")
		if not content and "prompt" in payload and "response" in payload:
			content = f"USER: {payload['prompt']}\n\nASSISTANT: {payload['response']}"
		return content, [point]

	from qdrant_client import models as _qm

	filter_conds: list[Any] = []
	if parent_id:
		filter_conds.append(_qm.FieldCondition(key="parent_id", match=_qm.MatchValue(value=parent_id)))
	elif source_buf_id:
		filter_conds.append(_qm.FieldCondition(key="source_buffer_id", match=_qm.MatchValue(value=source_buf_id)))

	sibling_points = []
	if filter_conds:
		try:
			sibling_points, _ = client.scroll(
				collection_name=collection,
				scroll_filter=_qm.Filter(must=filter_conds),
				limit=100,
				with_payload=True,
			)
		except Exception as e:
			logger.debug(f"[SLEEP ENGINE] Failed to fetch siblings for multi-chunk reassembly: {e}")
			sibling_points = []

	if not sibling_points:
		sibling_points = [point]

	def _get_idx(p):
		p_load = p.payload or {}
		p_meta = p_load.get("metadata", {}) if isinstance(p_load.get("metadata"), dict) else {}
		idx = p_load.get("chunk_index") if p_load.get("chunk_index") is not None else p_meta.get("chunk_index")
		return idx if isinstance(idx, int) else 0

	sorted_siblings = sorted(sibling_points, key=_get_idx)

	assembled_chunks = []
	for p in sorted_siblings:
		p_load = p.payload or {}
		text = p_load.get("content", "")
		if not text and "prompt" in p_load and "response" in p_load:
			text = f"USER: {p_load['prompt']}\n\nASSISTANT: {p_load['response']}"
		if text:
			assembled_chunks.append(text)

	full_text = "".join(assembled_chunks) if assembled_chunks else payload.get("content", "")
	return full_text, sorted_siblings


def _promote_lone_chunk_to_hub(memory_manager, client, chunk_col: str, chunk_id, distilled: dict) -> bool:
	"""A turn that distills to a single surviving chunk gets no synthesized hub,
	which left its content invisible to direct recall (sequence_chunk is
	structurally excluded from search). The lone chunk IS the turn's best
	distillate, so promote it to synthesis_hub and weave it into the thread."""
	try:
		client.set_payload(
			collection_name=chunk_col,
			payload={"lazarus_phase": "synthesis_hub", "node_type": "synthesis_hub", "promoted_from": "sequence_chunk"},
			points=[chunk_id],
		)
		if cfg.TEXTURE_SHADOW_ENABLED and distilled.get("texture"):
			try:
				memory_manager.add_texture_shadow(chunk_col, str(chunk_id), distilled["texture"])
			except Exception as e:
				logger.debug(f"[SLEEP ENGINE] texture shadow write failed for promoted chunk {chunk_id}: {e}")

		# Thread Weaving — the promoted chunk is this session's hub for its collection
		thread_state = _load_thread_state()
		prev_hub_id = thread_state.get(chunk_col)
		if prev_hub_id:
			client.set_payload(collection_name=chunk_col, payload={"prev_session_hub": prev_hub_id}, points=[chunk_id])
			client.set_payload(collection_name=chunk_col, payload={"next_session_hub": str(chunk_id)}, points=[prev_hub_id])
		thread_state[chunk_col] = str(chunk_id)
		_save_thread_state(thread_state)
		return True
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Lone-chunk promotion failed for {chunk_id} in {chunk_col}: {e}")
		return False


class ConsolidationPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "consolidation"

	@property
	def requires_gpu(self) -> bool:
		return True

	def execute(self, ctx: SleepContext) -> None:
		memory_manager = ctx.memory_manager
		client = memory_manager.client
		collection = "interaction_memories"
		new_work_hubs = []

		# Drain cutoff: only engrams inserted up to the moment the sleep started are
		# eligible this cycle. The SleepJobDriver pins it at job start (persisted in
		# the checkpoint); the one-shot pulse captures it here at phase start. Points
		# written by sessions still running during the sleep stay buffered for next
		# cycle — the drain loop is guaranteed to terminate.
		sleep_cutoff_ts = float(ctx.sleep_cutoff_ts or 0) or float(time.time())
		cutoff_enabled = getattr(cfg, "SLEEP_CUTOFF_ENABLED", True)
		if cutoff_enabled:
			logger.info(
				f"[SLEEP ENGINE] Drain bounded to engrams with timestamp <= {sleep_cutoff_ts:.0f} "
				f"({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sleep_cutoff_ts))})"
			)

		if not client.collection_exists(collection):
			logger.warning("Sleep cycle aborted: fast buffer does not exist.")
			return

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
				ctx.deferred = True
				return
			logger.debug(f"[SLEEP ENGINE] VRAM preflight OK: {_free_vram_mb} MB free ({_vram_backend}).")

		# LLM Health Check & Ephemeral Server
		ephemeral_server = EphemeralServer()
		if not _check_llm_available():
			logger.warning("[SLEEP ENGINE] Local LLM is offline. Launching Ephemeral Samantha Server...")
			try:
				if not ephemeral_server.start(memory_manager):
					return
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to start Ephemeral Server: {e}")
				return

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

			# Pause probe + live progress at every batch boundary: a pause request
			# from the operator is honored HERE (JobPauseRequested → the runner
			# seals PAUSED with the checkpoint intact; on resume the drain continues
			# with whatever remains, since processed points were already deleted).
			# The per-batch status write keeps `total_processed` visible in the
			# public file so a resumed cycle inherits the accumulated count.
			if ctx.pause_probe is not None:
				ctx.pause_probe()
			ctx.total_processed = total_processed
			from red_pill.metabolism.phases import SLEEP_PHASES as _sleep_phases

			ctx.update_status(self.name, status="running", phase_index=0, total_phases=len(_sleep_phases))

			if consecutive_llm_failures >= max_llm_failures:
				logger.error("[SLEEP ENGINE] Thermal breaker tripped. Aborting drain loop.")
				break

			if batch_number > 1 and not _check_llm_available():
				break

			try:
				from qdrant_client import models as _qm

				# mypy: Qdrant Filter acepta la union de condiciones (invariante),
				# asi que los acumuladores se tipan como list[Any].
				_must: list[Any] = [_qm.FieldCondition(key="timestamp", range=_qm.Range(lte=sleep_cutoff_ts))] if cutoff_enabled else []
				_must_not: list[Any] = [_qm.HasIdCondition(has_id=list(failed_ids))] if failed_ids else []
				if _must and _must_not:
					scroll_filter = Filter(must=_must, must_not=_must_not)
				elif _must:
					scroll_filter = Filter(must=_must)
				elif _must_not:
					scroll_filter = Filter(must_not=_must_not)
				else:
					scroll_filter = Filter()
				scroll_result, _ = client.scroll(collection_name=collection, scroll_filter=scroll_filter, limit=scroll_limit, with_payload=True)
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to fetch raw buffer: {e}")
				break

			if not scroll_result:
				break

			batch_processed = 0
			batch_processed_ids = set()
			for point in scroll_result:
				raw_id = point.id
				if raw_id in batch_processed_ids:
					continue

				# Pause probe PER POINT: una noche entera suele ser UN único batch
				# (el scroll cabe en el límite), así que una frontera por batch
				# sellaría la pausa solo al final del drenaje. Aquí la pausa del
				# operador se honra en el siguiente punto (~segundos, no horas).
				if ctx.pause_probe is not None:
					ctx.pause_probe()

				raw_text, sibling_points = reassemble_raw_sequence(client, collection, point)
				sibling_ids = [p.id for p in sibling_points]
				for s_id in sibling_ids:
					batch_processed_ids.add(s_id)

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
				last_chunk_col = None
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
				fragment_affects = []
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
						chunk_metadata = {
							"lazarus_phase": "sequence_chunk",
							"distiller_version": "v3",
							"hub_depth": 1,
							"source_buffer_id": raw_id,
							"model": model_name,
							"parent_id": parent_id,
							"category_reviewed_at": time.time(),
						}
						if distilled.get("texture"):
							chunk_metadata["texture"] = distilled["texture"]
						if distilled.get("lang"):
							chunk_metadata["lang"] = distilled["lang"]
						if distilled.get("relics"):
							chunk_metadata["relics"] = distilled["relics"]
						new_id = memory_manager.add_memory(
							collection=chunk_col,
							text=summary,
							metadata=chunk_metadata,
							color="blue" if chunk_col == "work_memories" else "purple",
							emotion=distilled.get("emotion", "neutral"),
							intensity=distilled.get("intensity", 0.5),
						)
						if prev_chunk_id and new_id:
							client.set_payload(collection_name=chunk_col, payload={"associations": [prev_chunk_id]}, points=[new_id])
						if new_id:
							prev_chunk_id = new_id
							last_chunk_col = chunk_col
							child_ids.append(new_id)
							fragment_affects.append(
								{
									"child_id": str(new_id),
									"emotion": distilled.get("emotion", "neutral"),
									"intensity": distilled.get("intensity", 0.5),
									"category": distilled.get("category", fallback_cat),
								}
							)
							batch_processed += 1
							chunks_saved += 1
					except Exception as e:
						logger.error(f"[SLEEP ENGINE] Metabolic Fixation failed for {raw_id}: {e}")
						point_write_failed = True

				# Hub Synthesis (v2: texture + language preserving, affect from history)
				if len(surviving_chunks) > 1 and prev_chunk_id and not point_write_failed:
					max_chunks_per_hub = getattr(cfg, "SLEEP_MAX_CHUNKS_PER_HUB", 6)
					if len(surviving_chunks) > max_chunks_per_hub:
						chunk_batches = [surviving_chunks[k : k + max_chunks_per_hub] for k in range(0, len(surviving_chunks), max_chunks_per_hub)]
						affects_batches = [fragment_affects[k : k + max_chunks_per_hub] for k in range(0, len(fragment_affects), max_chunks_per_hub)]
					else:
						chunk_batches = [surviving_chunks]
						affects_batches = [fragment_affects]

					for b_idx, (c_batch, a_batch) in enumerate(zip(chunk_batches, affects_batches)):
						hub = synthesize_hub_v2(c_batch)
						hub_summary = f"{hub['title']}\n{hub['summary']}" if hub.get("title") else hub["summary"]
						if len(chunk_batches) > 1:
							hub_summary = f"[Parte {b_idx + 1}/{len(chunk_batches)}] {hub_summary}"

						hub_emotion, hub_intensity = derive_hub_affect(c_batch)
						max_child_depth = max(
							[int(c.get("hub_depth", 1)) for c in c_batch if isinstance(c, dict) and str(c.get("hub_depth", "")).isdigit()], default=1
						)
						hub_metadata = {
							"lazarus_phase": "synthesis_hub",
							"node_type": "synthesis_hub",
							"distiller_version": "v3",
							"hub_depth": max_child_depth + 1,
							"source_buffer_id": raw_id,
							"model": model_name,
							"parent_id": parent_id,
							"emotional_vector": build_emotional_vector(a_batch),
							"category_reviewed_at": time.time(),
						}
						if hub.get("texture"):
							hub_metadata["texture"] = hub["texture"]
						if hub.get("lang"):
							hub_metadata["lang"] = hub["lang"]
						hub_relics = merge_relics(c_batch)
						if hub_relics:
							hub_metadata["relics"] = hub_relics
						try:
							hub_id = memory_manager.add_memory(
								collection=target_col,
								text=hub_summary,
								metadata=hub_metadata,
								color="cyan",
								emotion=hub_emotion,
								intensity=hub_intensity,
							)
							if hub_id:
								client.set_payload(collection_name=target_col, payload={"associations": [prev_chunk_id]}, points=[hub_id])
								if cfg.TEXTURE_SHADOW_ENABLED and hub.get("texture"):
									try:
										memory_manager.add_texture_shadow(target_col, str(hub_id), hub["texture"])
									except Exception as e:
										logger.debug(f"[SLEEP ENGINE] texture shadow write failed for {hub_id}: {e}")
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
						except Exception as e:
							logger.error(f"[SLEEP ENGINE] Failed to save multi-batch hub: {e}")
				elif len(surviving_chunks) == 1 and prev_chunk_id and not point_write_failed:
					# Single-survivor turn: promote the lone chunk to hub so the turn
					# keeps a searchable representative (no LLM synthesis needed).
					lone_col = last_chunk_col or target_col
					if _promote_lone_chunk_to_hub(memory_manager, client, lone_col, prev_chunk_id, surviving_chunks[0]):
						if lone_col == "work_memories":
							new_work_hubs.append(surviving_chunks[0].get("summary", ""))

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

						client.delete(collection_name=collection, points_selector=sibling_ids)
					except Exception as e:
						logger.error(f"[SLEEP ENGINE] Failed to save raw parent engram: {e}")
						point_write_failed = True
				elif not point_llm_failed and not point_write_failed:
					client.delete(collection_name=collection, points_selector=sibling_ids)

				# Any raw point NOT deleted this pass would be re-scrolled and re-distilled into a
				# fresh parent next batch — record it so the scroll filter skips it (no duplicates).
				if point_write_failed or point_llm_failed:
					for s_id in sibling_ids:
						failed_ids.add(s_id)

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
						# Staging files written after the cutoff belong to the NEXT cycle.
						if os.path.getmtime(filepath) > sleep_cutoff_ts:
							logger.debug(f"[SLEEP ENGINE] Staging file {filename} written after cutoff; deferring to next cycle.")
							continue
					except OSError:
						pass
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
					last_chunk_col = None
					fragment_affects = []

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
							chunk_metadata = {
								"lazarus_phase": "sequence_chunk",
								"source_buffer_id": raw_id,
								"model": model_name,
								"parent_id": parent_id,
								"category_reviewed_at": time.time(),
								**ws_meta,
							}
							if distilled.get("texture"):
								chunk_metadata["texture"] = distilled["texture"]
							if distilled.get("lang"):
								chunk_metadata["lang"] = distilled["lang"]
							if distilled.get("relics"):
								chunk_metadata["relics"] = distilled["relics"]
							new_id = memory_manager.add_memory(
								collection=chunk_col,
								text=summary,
								metadata=chunk_metadata,
								color="blue" if chunk_col == "work_memories" else "purple",
								emotion=distilled.get("emotion", "neutral"),
								intensity=distilled.get("intensity", 0.5),
							)
							if prev_chunk_id and new_id:
								client.set_payload(collection_name=chunk_col, payload={"associations": [prev_chunk_id]}, points=[new_id])
							if new_id:
								prev_chunk_id = new_id
								last_chunk_col = chunk_col
								child_ids.append(new_id)
								fragment_affects.append(
									{
										"child_id": str(new_id),
										"emotion": distilled.get("emotion", "neutral"),
										"intensity": distilled.get("intensity", 0.5),
										"category": distilled.get("category", "work"),
									}
								)
								total_processed += 1
						except Exception:
							pass

					# Hub Synthesis (v2)
					if len(surviving_chunks) > 1 and prev_chunk_id:
						hub = synthesize_hub_v2(surviving_chunks)
						hub_summary = f"{hub['title']}\n{hub['summary']}" if hub.get("title") else hub["summary"]
						hub_emotion, hub_intensity = derive_hub_affect(surviving_chunks)
						hub_metadata = {
							"lazarus_phase": "synthesis_hub",
							"node_type": "synthesis_hub",
							"source_buffer_id": raw_id,
							"model": model_name,
							"parent_id": parent_id,
							"emotional_vector": build_emotional_vector(fragment_affects),
							"category_reviewed_at": time.time(),
							**ws_meta,
						}
						if hub.get("texture"):
							hub_metadata["texture"] = hub["texture"]
						if hub.get("lang"):
							hub_metadata["lang"] = hub["lang"]
						hub_relics = merge_relics(surviving_chunks)
						if hub_relics:
							hub_metadata["relics"] = hub_relics
						try:
							hub_id = memory_manager.add_memory(
								collection="work_memories",
								text=hub_summary,
								metadata=hub_metadata,
								color="cyan",
								emotion=hub_emotion,
								intensity=hub_intensity,
							)
							if hub_id:
								client.set_payload(collection_name="work_memories", payload={"associations": [prev_chunk_id]}, points=[hub_id])
								if cfg.TEXTURE_SHADOW_ENABLED and hub.get("texture"):
									try:
										memory_manager.add_texture_shadow("work_memories", str(hub_id), hub["texture"])
									except Exception as e:
										logger.debug(f"[SLEEP ENGINE] texture shadow write failed for {hub_id}: {e}")
								child_ids.append(hub_id)
								new_work_hubs.append(hub_summary)

								# Thread Weaving
								thread_state = _load_thread_state()
								prev_hub_id = thread_state.get("work_memories")
								if prev_hub_id:
									client.set_payload(collection_name="work_memories", payload={"prev_session_hub": prev_hub_id}, points=[hub_id])
									client.set_payload(
										collection_name="work_memories", payload={"next_session_hub": str(hub_id)}, points=[prev_hub_id]
									)
								thread_state["work_memories"] = str(hub_id)
								_save_thread_state(thread_state)
						except Exception:
							pass
					elif len(surviving_chunks) == 1 and prev_chunk_id:
						# Single-survivor staging cascade: same promotion as the drain loop.
						lone_col = last_chunk_col or "work_memories"
						if _promote_lone_chunk_to_hub(memory_manager, client, lone_col, prev_chunk_id, surviving_chunks[0]):
							if lone_col == "work_memories":
								new_work_hubs.append(surviving_chunks[0].get("summary", ""))

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

		ephemeral_server.stop(memory_manager, total_processed)
		ctx.total_processed = total_processed
