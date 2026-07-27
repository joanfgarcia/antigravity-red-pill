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
		murky_pointers = 0
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
					# Self-evocation audit (report-only, operator's book test): a memory
					# that is ONLY an opaque pointer is murky — count it, never touch it.
					if _is_murky_pointer(str(payload.get("content", ""))):
						murky_pointers += 1
					continue
				if payload.get("immune") and not payload.get("_is_fragment"):
					# A deliberate immune anchor with no content is an anomaly for the
					# operator. Fragment shrapnel, however, only INHERITED its immunity
					# (force_immune cascades from the parent verbatim) — it protects
					# nothing and gets purged like any other empty.
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

		report[collection] = {
			"empty_purged": len(victims),
			"chains_restitched": restitched,
			"skipped_immune_empty": skipped_immune,
			"murky_pointers": murky_pointers,
		}
		if victims or skipped_immune or murky_pointers:
			logger.info(
				f"[HYGIENE] {collection}: {len(victims)} empty engrams {'found' if dry_run else 'purged'} "
				f"({restitched} chain links restitched, {skipped_immune} immune empties and "
				f"{murky_pointers} murky pointers reported for the operator)."
			)
	return report


_NOISE_MARKERS = ("[TOOL USE:", "[TOOL RESULT:")
_DIALOG_PREFIXES = ("USER:", "ASSISTANT:", "Operator Prompt:", "AI Response Node:")


def _tool_noise_ratio(full_text: str) -> float:
	"""Fraction of characters inside legacy tool-dump blocks.

	Line state machine: a line starting a [TOOL USE:/[TOOL RESULT: block is noise;
	following lines stay noise until a dialog prefix or a new block starts
	(legacy TOOL RESULT dumps span lines with no terminator). Role prefixes
	glued to a marker ("ASSISTANT: [TOOL USE:...") count as noise too.
	"""
	if not full_text.strip():
		return 1.0
	noise_chars = 0
	in_result_block = False
	for line in full_text.splitlines(keepends=True):
		stripped = line.strip()
		body = stripped
		for prefix in _DIALOG_PREFIXES:
			if stripped.startswith(prefix):
				body = stripped[len(prefix) :].strip()
				break
		if any(body.startswith(m) for m in _NOISE_MARKERS):
			noise_chars += len(line)
			in_result_block = body.startswith("[TOOL RESULT:")
			continue
		if stripped.startswith(_DIALOG_PREFIXES) and body and not any(body.startswith(m) for m in _NOISE_MARKERS):
			in_result_block = False  # real dialog resumes
			continue
		if in_result_block or not stripped:
			noise_chars += len(line) if in_result_block else 0
			continue
	return noise_chars / max(1, len(full_text))


def purge_tool_noise_raw_parents(
	memory_manager,
	collections=("work_memories", "social_memories"),
	dry_run: bool = True,
	noise_threshold: float = 0.9,
	max_residual_chars: int = 200,
) -> dict:
	"""Purge legacy verbatim families that are overwhelmingly tool-dump noise.

	Judged at FAMILY level (anchor + fragments reassembled by chunk_index): a
	fragment mid-JSON carries no marker, so per-fragment classification would
	either miss it or need dangerous code-vs-noise guessing. A family is purged
	only if noise ratio >= threshold AND the residual real text is under
	max_residual_chars — mixed conversations that merely contain tool calls are
	kept whole. The raw chain is restitched around each purged anchor.
	Chronicle's compact markers (CHRONICLE_STRIP_TOOL_PAYLOADS) make new noise
	impossible; this cleans what entered before the filter existed.
	"""
	from qdrant_client import models as qm

	client = memory_manager.client
	report: dict = {}

	for collection in collections:
		if not client.collection_exists(collection):
			continue
		families: dict = {}
		offset = None
		scroll_filter = qm.Filter(must=[qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value="raw_parent"))])
		while True:
			try:
				points, offset = client.scroll(
					collection_name=collection, scroll_filter=scroll_filter, limit=512, offset=offset, with_payload=True, with_vectors=False
				)
			except Exception as e:
				logger.error(f"[NOISE PURGE] scroll failed in {collection}: {e}")
				break
			for p in points:
				payload = p.payload or {}
				family_id = str(payload.get("parent_id") or p.id)
				families.setdefault(family_id, []).append((payload.get("chunk_index", 0) or 0, str(p.id), payload))
			if offset is None:
				break

		purged_points = 0
		purged_families = 0
		kept_mixed = 0
		for family_id, members in families.items():
			members.sort(key=lambda t: t[0])
			full_text = "".join(str(pay.get("content", "")) for _, _, pay in members)
			ratio = _tool_noise_ratio(full_text)
			residual = len(full_text) * (1.0 - ratio)
			if ratio < noise_threshold or residual > max_residual_chars:
				if ratio > 0.3:
					kept_mixed += 1
				continue
			purged_families += 1
			purged_points += len(members)
			if dry_run:
				continue
			anchor_payload = next((pay for _, pid, pay in members if pid == family_id), members[0][2])
			try:
				prev_id = anchor_payload.get("prev_raw_parent")
				next_id = anchor_payload.get("next_raw_parent")
				if prev_id:
					if next_id:
						client.set_payload(collection_name=collection, payload={"next_raw_parent": str(next_id)}, points=[prev_id])
					else:
						client.delete_payload(collection_name=collection, keys=["next_raw_parent"], points=[prev_id])
				if next_id:
					if prev_id:
						client.set_payload(collection_name=collection, payload={"prev_raw_parent": str(prev_id)}, points=[next_id])
					else:
						client.delete_payload(collection_name=collection, keys=["prev_raw_parent"], points=[next_id])
			except Exception as e:
				logger.debug(f"[NOISE PURGE] chain restitch failed around {family_id}: {e}")
			try:
				client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=[pid for _, pid, _ in members]))
			except Exception as e:
				logger.error(f"[NOISE PURGE] delete failed for family {family_id} in {collection}: {e}")

		report[collection] = {
			"families_scanned": len(families),
			"families_purged": purged_families,
			"points_purged": purged_points,
			"mixed_kept": kept_mixed,
			"dry_run": dry_run,
		}
		logger.info(f"[NOISE PURGE] {collection}: {report[collection]}")
	return report


def compact_tool_noise(text: str) -> str:
	"""Retroactively apply the Chronicle compact-marker filter to a reassembled
	verbatim: dialog survives byte-exact; legacy [TOOL USE: name({json})] lines
	collapse to self-evocative markers and TOOL RESULT blocks keep only their
	head (where verdicts live). Self-evocation principle: the memory must let
	you intuit what it pointed to even when the artifact is gone."""
	import json as json_lib
	import re

	from red_pill.metabolism.chronicle.claude_code_plugin import _render_tool_result, _render_tool_use

	out: list = []
	result_buf: list = []

	def flush_result() -> None:
		if result_buf:
			body = "\n".join(result_buf)
			inner = body[len("[TOOL RESULT:") :].strip() if body.startswith("[TOOL RESULT:") else body
			out.append(_render_tool_result("", inner.rstrip("]")))
			result_buf.clear()

	for line in text.splitlines():
		stripped = line.strip()
		role = ""
		body = stripped
		for prefix in _DIALOG_PREFIXES:
			if stripped.startswith(prefix):
				role = prefix + " "
				body = stripped[len(prefix) :].strip()
				break
		if body.startswith("[TOOL USE:"):
			flush_result()
			match = re.match(r"\[TOOL USE: (\w+)\((.*)\)\]\s*$", body)
			if match:
				try:
					inp = json_lib.loads(match.group(2))
				except Exception:
					inp = {}
				out.append(role + _render_tool_use(match.group(1), inp if isinstance(inp, dict) else {}))
			else:
				name = body[len("[TOOL USE:") :].strip().split("(")[0].strip() or "unknown"
				out.append(role + _render_tool_use(name, {}))
			continue
		if body.startswith("[TOOL RESULT:"):
			flush_result()
			result_buf.append((role + body) if role else body)
			continue
		if result_buf and stripped and not role:
			result_buf.append(line)
			continue
		flush_result()
		out.append(line)
	flush_result()
	return "\n".join(out)


_MURKY_TOKEN = None


def _is_murky_pointer(content: str) -> bool:
	"""A murky memory: content that is essentially ONLY an opaque reference
	(path, url, uuid, buffer id) with no semantic residue to intuit the referent."""
	import re

	stripped = content.strip()
	if not stripped or len(stripped) > 200:
		return False
	tokens = re.sub(
		r"(https?://\S+|/[\w./-]{4,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|claude_code_[\w-]+|" + "file" + r":///\S+)",
		" ",
		stripped,
	)

	residue_words = [w for w in re.findall(r"[A-Za-zÀ-ÿ]{3,}", tokens)]
	return tokens != stripped and len(residue_words) < 4


def rewrite_tool_noise_families(
	memory_manager,
	collections=("work_memories", "social_memories"),
	dry_run: bool = True,
	min_noise_ratio: float = 0.3,
	min_gain: float = 0.2,
) -> dict:
	"""Surgical compaction of MIXED verbatim families (operator-ratified):
	reassemble by chunk_index, compact tool noise, re-store under the SAME
	anchor id preserving chain, created_at, immunity and provenance. Families
	below min_noise_ratio or whose compaction gains < min_gain are untouched."""
	from qdrant_client import models as qm

	client = memory_manager.client
	report: dict = {}

	for collection in collections:
		if not client.collection_exists(collection):
			continue
		families: dict = {}
		offset = None
		scroll_filter = qm.Filter(must=[qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value="raw_parent"))])
		while True:
			try:
				points, offset = client.scroll(
					collection_name=collection, scroll_filter=scroll_filter, limit=512, offset=offset, with_payload=True, with_vectors=False
				)
			except Exception as e:
				logger.error(f"[NOISE REWRITE] scroll failed in {collection}: {e}")
				break
			for p in points:
				payload = p.payload or {}
				family_id = str(payload.get("parent_id") or p.id)
				families.setdefault(family_id, []).append((payload.get("chunk_index", 0) or 0, str(p.id), payload))
			if offset is None:
				break

		rewritten = 0
		chars_before = 0
		chars_after = 0
		for family_id, members in families.items():
			members.sort(key=lambda t: t[0])
			full_text = "".join(str(pay.get("content", "")) for _, _, pay in members)
			if _tool_noise_ratio(full_text) < min_noise_ratio:
				continue
			compacted = compact_tool_noise(full_text)
			if len(compacted) >= len(full_text) * (1.0 - min_gain):
				continue
			rewritten += 1
			chars_before += len(full_text)
			chars_after += len(compacted)
			if dry_run:
				continue
			anchor_payload = next((pay for _, pid, pay in members if pid == family_id), members[0][2])
			preserved = {
				k: anchor_payload[k]
				for k in ("created_at", "source_buffer_id", "model", "prev_raw_parent", "next_raw_parent", "originator")
				if anchor_payload.get(k) is not None
			}
			try:
				client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=[pid for _, pid, _ in members]))
				new_id = memory_manager.add_memory(
					collection=collection,
					text=compacted,
					point_id=family_id,
					metadata={"lazarus_phase": "raw_parent", "rewritten_from": "tool_noise_compaction", "original_chars": len(full_text)},
					force_immune=bool(anchor_payload.get("immune")),
				)
				if new_id:
					client.set_payload(collection_name=collection, payload=preserved, points=[family_id])
			except Exception as e:
				logger.error(f"[NOISE REWRITE] rewrite failed for family {family_id} in {collection}: {e}")

		report[collection] = {
			"families_rewritten": rewritten,
			"chars_before": chars_before,
			"chars_after": chars_after,
			"dry_run": dry_run,
		}
		logger.info(f"[NOISE REWRITE] {collection}: {report[collection]}")
	return report


def cleanup_orphan_raw_parents(memory_manager, collections=("work_memories", "social_memories")) -> dict:
	"""
	Garbage collection routine for raw_parent engrams:
	When all synthesized child engrams (sequence_chunks / synthesis_hubs) associated with
	a raw_parent have eroded away due to lack of recall/utility, the raw_parent
	no longer has active children in the memory graph and is safely garbage collected
	(since the raw verbatim interaction is already archived in archive_memories).
	"""
	from qdrant_client import models as qm

	client = memory_manager.client
	report = {}

	for col in collections:
		if not client.collection_exists(col):
			continue

		try:
			raw_parents, _ = client.scroll(
				collection_name=col,
				scroll_filter=qm.Filter(must=[qm.FieldCondition(key="lazarus_phase", match=qm.MatchValue(value="raw_parent"))]),
				limit=500,
				with_payload=True,
			)
		except Exception as e:
			logger.error(f"[GARBAGE COLLECTION] Failed to scroll raw_parents in {col}: {e}")
			continue

		deleted_count = 0
		for parent in raw_parents:
			payload = parent.payload or {}
			child_ids = payload.get("associations", [])
			if not child_ids or not isinstance(child_ids, list):
				continue

			# Retrieve existing children in Qdrant
			try:
				existing = client.retrieve(collection_name=col, ids=child_ids, with_payload=False)
			except Exception:
				existing = []

			if not existing:
				# All child engrams have eroded away — safe to remove orphan raw_parent
				try:
					client.delete(collection_name=col, points_selector=qm.PointIdsList(points=[parent.id]))
					deleted_count += 1
				except Exception as e:
					logger.error(f"[GARBAGE COLLECTION] Failed to delete orphan raw_parent {parent.id}: {e}")

		report[col] = deleted_count
		if deleted_count > 0:
			logger.info(f"[GARBAGE COLLECTION] Cleaned up {deleted_count} orphan raw_parent(s) in {col}.")

	return report
