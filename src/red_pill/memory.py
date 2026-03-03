import hashlib
import json
import logging
import os
import socket
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

try:
	from fastembed import TextEmbedding
except ImportError:
	TextEmbedding = Any  # type: ignore

import red_pill.config as cfg
from red_pill.hive import HiveMind
from red_pill.schemas import CreateEngramRequest
from red_pill.utils.affect import get_emotional_stability_multiplier
from red_pill.utils.emotion import get_chroma_for_emotion, get_emotion, get_emotions
from red_pill.utils.fragmentation import synaptic_split
from red_pill.utils.pulse import record_interaction

logger = logging.getLogger(__name__)


def _mask_pii_exception(e: Exception) -> str:
	"""Truncates exception strings to prevent payload PII leaks."""
	msg = str(e)
	return msg if len(msg) < 150 else msg[:150] + "... [TRUNCATED]"


class PointUpdate:
	"""Internal helper for point updates."""

	def __init__(self, id: Any, payload: Dict[str, Any]):
		self.id = id
		self.payload = payload


class MemoryManager:
	"""B760-Adaptive memory engine."""

	def __init__(self, url: str = cfg.QDRANT_URL):
		self.client = QdrantClient(url=url, api_key=cfg.QDRANT_API_KEY)
		self.encoder: Optional[TextEmbedding] = None
		self._reinforce_lock = threading.Lock()
		self._metabolism_thread: Optional[threading.Thread] = None
		self.hive = HiveMind()

	def _get_vector_from_daemon(self, text: str) -> Optional[List[float]]:
		"""Retrieves embedding from the memory sidecar socket."""
		socket_path = cfg.DAEMON_SOCKET_PATH
		if not os.path.exists(socket_path):
			return None

		try:
			with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
				client.settimeout(2.0)
				client.connect(socket_path)

				# SEC-002 & SEC-004: Auth & Payload
				request = {"text": text, "api_key": cfg.SIDECAR_AUTH_KEY}
				payload = json.dumps(request).encode("utf-8")

				# CQ-003: Length-prefixed framing
				header = len(payload).to_bytes(4, byteorder="big")
				client.sendall(header + payload)

				# Read response header
				resp_header = client.recv(4)
				if not resp_header:
					return None
				resp_len = int.from_bytes(resp_header, byteorder="big")

				resp_data = b""
				while len(resp_data) < resp_len:
					chunk = client.recv(min(resp_len - len(resp_data), 8192))
					if not chunk:
						break
					resp_data += chunk

				if resp_data:
					response = json.loads(resp_data.decode("utf-8"))
					if response.get("status") == "ok":
						return response.get("vector") if response.get("vector") is not None else None
					else:
						logger.error(f"Daemon error: {response.get('message')}")
		except Exception as e:
			logger.debug(f"Sidecar connection failed: {e}")
		return None

	def _get_vector(self, text: str) -> List[float]:
		"""Optimized vector retrieval with daemon-first priority."""
		vector = self._get_vector_from_daemon(text)
		if vector:
			return vector

		if self.encoder is None:
			try:
				from fastembed import TextEmbedding

				providers = [cfg.EXECUTION_PROVIDER] if cfg.EXECUTION_PROVIDER else None
				self.encoder = TextEmbedding(model_name=cfg.EMBEDDING_MODEL, providers=providers)
			except ImportError:
				raise RuntimeError("FastEmbed library is missing. All semantic memory operations are blocked.")

		assert self.encoder is not None
		return list(self.encoder.embed([text]))[0].tolist()  # type: ignore

	def add_memory(
		self,
		collection: str,
		text: str,
		importance: float = 1.0,
		metadata: Optional[Dict[str, Any]] = None,
		point_id: Optional[str] = None,
		color: str = cfg.DEFAULT_COLOR,
		emotion: str = cfg.DEFAULT_EMOTION,
		intensity: float = 1.0,
		force_immune: bool = False,
	) -> str:
		"""Stores a new engram with B760 validation and emotional chroma."""
		# SEC-001 & SEC-008: Validation via Pydantic schema

		# SEC-001: Strip reserved keys before validation to ensure robustness
		metadata = (metadata or {}).copy()
		for key in CreateEngramRequest.RESERVED_KEYS:
			metadata.pop(key, None)

		try:
			req = CreateEngramRequest(
				content=text,
				importance=importance,
				color=color,  # type: ignore
				emotion=emotion,  # type: ignore
				intensity=intensity,
				metadata=metadata or {},
			)
			# Update values from validated request
			text = req.content
			importance = req.importance
			metadata = req.metadata
			color = req.color
			emotion = req.emotion
			intensity = req.intensity
		except Exception as e:
			raise ValueError(f"Invalid engram data: {e}")

		# v5.4.0: Temporal Pulse Detection
		pulse = record_interaction()

		# v5.5.0: Synaptic Fragmentation (Anti-Amnesia Logic)
		# If the text is a massive block, we split it into sinaptic fragments
		# to ensure vectors are granular and searchable.
		if len(text) > cfg.CHUNK_THRESHOLD and not metadata.get("_is_fragment"):
			fragments = synaptic_split(text)
			parent_id = point_id if point_id else str(uuid.uuid4())

			# 1. Store the first fragment as the 'Anchor' (Original ID)
			for i, frag in enumerate(fragments):
				frag_metadata = metadata.copy()
				frag_metadata["_is_fragment"] = True
				frag_metadata["parent_id"] = parent_id
				frag_metadata["chunk_index"] = i
				frag_metadata["total_chunks"] = len(fragments)

				# The first fragment keeps the requested point_id (if any)
				current_frag_id = parent_id if i == 0 else str(uuid.uuid4())

				self.add_memory(
					collection=collection,
					text=frag,
					importance=importance,
					metadata=frag_metadata,
					point_id=current_frag_id,
					color=color,
					emotion=emotion,
					intensity=intensity,
					force_immune=force_immune,
				)

			# Return the ID of the anchor point
			return parent_id
		metadata["pulse_status"] = pulse["status"]
		metadata["pulse_delta"] = pulse["delta_seconds"]

		# v5.4.0: Advanced Multi-Emotion Profile
		emotional_profile = []
		if os_detect := os.getenv("EMOTION_AUTO_DETECT", "True").lower() == "true":
			if cfg.MULTI_EMOTION_INFERENCE:
				emotional_profile = get_emotions(text)

			if emotional_profile and emotion == cfg.DEFAULT_EMOTION:
				emotion = emotional_profile[0]["label"]
				if color == cfg.DEFAULT_COLOR:
					color = get_chroma_for_emotion(emotion)
			elif os_detect and emotion == cfg.DEFAULT_EMOTION:
				# Fallback to single if multi is disabled but detect is on
				detected = get_emotion(text)
				if detected:
					emotion = detected
					if color == cfg.DEFAULT_COLOR:
						color = get_chroma_for_emotion(emotion)

		if emotional_profile:
			metadata["emotional_profile"] = emotional_profile

		validated_request = CreateEngramRequest(
			content=text,
			importance=importance,
			color=color,  # type: ignore
			emotion=emotion,  # type: ignore
			intensity=intensity,
			metadata=metadata,
		)

		text = validated_request.content
		importance = validated_request.importance
		clean_metadata = validated_request.metadata

		actual_id = point_id if point_id else str(uuid.uuid4())
		vector = self._get_vector(text)

		for key in CreateEngramRequest.RESERVED_KEYS:
			clean_metadata.pop(key, None)

		# Emotional Seed Score (B760-Native Emotional Seed Scoring, v4.2.1)
		# High-intensity emotional memories deserve a higher initial score so the
		# emotional decay multiplier does not kill them too fast.
		# Formula: score = importance * (1 + intensity_factor * color_multiplier * SEED_FACTOR)
		# Capped at IMMUNITY_THRESHOLD * 0.9 so single reinforcement can push to immunity.
		_emotion = validated_request.emotion
		_intensity = validated_request.intensity
		_color = validated_request.color
		if _emotion != "neutral" and _intensity > 1.0:
			_color_mult = cfg.EMOTIONAL_DECAY_MULTIPLIERS.get(_color, 1.0)
			_bonus = (_intensity / 10.0) * _color_mult * cfg.EMOTIONAL_SEED_FACTOR
			_initial_score = importance * (1.0 + _bonus)
		else:
			_initial_score = importance
		_initial_score = round(min(_initial_score, cfg.IMMUNITY_THRESHOLD * 0.9), 2)

		# If it was forced immune during seeding, set score to max
		if force_immune:
			_initial_score = cfg.IMMUNITY_THRESHOLD

		payload = {
			"content": text,
			"importance": importance,
			"reinforcement_score": _initial_score,
			"created_at": time.time(),
			"last_recalled_at": time.time(),
			"immune": force_immune,
			"color": validated_request.color,
			"emotion": validated_request.emotion,
			"intensity": validated_request.intensity,
			"schema_version": cfg.CURRENT_SCHEMA_VERSION,
			**clean_metadata,
		}

		try:
			self.client.upsert(collection_name=collection, points=[models.PointStruct(id=actual_id, vector=vector, payload=payload)])

			# Hive Mind Transmission (v5.0.0)
			# Only transmit non-immune technical or social findings to the collective.
			if not force_immune and collection in ["work_memories", "social_memories"]:
				self.hive.transmit_experience(
					collection_name=f"hive_{collection}",
					content=text,
					vector=vector,
					metadata={"importance": importance, "agent_id": os.getenv("AGENT_ID", "standalone")},
				)

			if cfg.METABOLISM_ENABLED:
				self._trigger_metabolism()
			return actual_id
		except Exception as e:
			logger.error(f"Failed to add memory: {_mask_pii_exception(e)}")
			return ""

	def update_memory(
		self,
		collection: str,
		point_id: str,
		color: Optional[str] = None,
		emotion: Optional[str] = None,
		intensity: Optional[float] = None,
	) -> bool:
		"""Updates engram attributes without re-embedding."""
		try:
			points = self.client.retrieve(collection_name=collection, ids=[point_id], with_payload=True, with_vectors=False)
			if not points:
				logger.warning(f"Memory {point_id} not found in {collection}")
				return False

			p = points[0]
			if p.payload is None:
				return False

			update_payload: dict[str, Any] = {}
			if color:
				update_payload["color"] = color
			if emotion:
				update_payload["emotion"] = emotion
			if intensity is not None:
				update_payload["intensity"] = intensity

			if update_payload:
				self.client.set_payload(collection_name=collection, payload=update_payload, points=[point_id])
			return True
		except Exception as e:
			logger.error(f"Failed to update memory {point_id}: {e}")
			return False

	def _trigger_metabolism(self) -> None:
		"""Persistent background process to check and execute erosion."""
		if self._metabolism_thread is not None and self._metabolism_thread.is_alive():
			return

		try:
			self._metabolism_thread = threading.Thread(target=self._run_metabolism_cycle, daemon=True)
			self._metabolism_thread.start()
		except Exception as e:
			logger.error(f"Metabolism thread launch failed: {e}")

	def _read_metabolism_state(self, f) -> tuple[float, bool]:  # type: ignore[type-arg]
		"""
		Reads metabolism state from an open file handle.

		State format (v5.5.0): JSON dict with keys:
			- last_run: float (Unix timestamp)
			- skip_next_erosion: bool (CQ-001 flag — set after TTL refresh)

		Backward-compatible: bare float strings (legacy format) are still parsed.

		Returns:
			(last_run, skip_next_erosion)
		"""
		f.seek(0)
		content = f.read().strip()
		if not content:
			return 0.0, False
		try:
			state = json.loads(content)
			if isinstance(state, dict):
				return float(state.get("last_run", 0.0)), bool(state.get("skip_next_erosion", False))
			# Legacy: bare float string
			return float(state), False
		except (ValueError, TypeError, json.JSONDecodeError):
			return 0.0, False

	def _write_metabolism_state(self, f, last_run: float, skip_next_erosion: bool = False) -> None:
		"""
		Writes metabolism state as JSON to an open, locked file handle.

		Args:
			f: Open file handle (must be locked and writable)
			last_run: Unix timestamp of this cycle
			skip_next_erosion: CQ-001 flag — if True, the next cycle will skip erosion
		"""
		f.seek(0)
		f.truncate()
		json.dump({"last_run": last_run, "skip_next_erosion": skip_next_erosion}, f)
		f.flush()

	def _run_metabolism_cycle(self) -> None:
		"""Internal metabolism loop with cooldown check.

		CQ-001: State file now carries a `skip_next_erosion` flag. When the
		Absence Guard runs `_refresh_ttl_timestamps()`, it sets this flag to
		protect freshly-refreshed engrams from being eroded on the very next
		cycle. The flag is consumed (cleared) at the start of the following run.
		"""
		state_file = cfg.METABOLISM_STATE_FILE
		now = time.time()

		try:
			try:
				import fcntl

				has_fcntl = True
			except ImportError:
				has_fcntl = False

			with open(state_file, "a+") as f:
				if has_fcntl:
					try:
						fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
					except BlockingIOError:
						return

				last_run, skip_next_erosion = self._read_metabolism_state(f)
				gap = now - last_run if last_run > 0 else float("inf")

				# --- Cooldown gate ---
				if last_run > 0 and gap < cfg.METABOLISM_COOLDOWN:
					if has_fcntl:
						fcntl.flock(f, fcntl.LOCK_UN)
					return

				# --- Absence guard ---
				if last_run > 0 and gap > cfg.ABSENCE_THRESHOLD:
					logger.warning(
						f"Absence detected ({gap / 86400:.1f} days). Running TTL refresh to protect the Bunker. "
						f"Erosion skipped for this cycle and the next."
					)
					for coll in cfg.METABOLISM_AUTO_COLLECTIONS:
						try:
							self._refresh_ttl_timestamps(coll.strip())
						except Exception as e:
							logger.error(f"TTL refresh failed during absence recovery for {coll}: {e}")

					# CQ-001: persist skip_next_erosion=True so the following
					# cycle also skips erosion, protecting freshly-refreshed engrams.
					self._write_metabolism_state(f, now, skip_next_erosion=True)
					if has_fcntl:
						fcntl.flock(f, fcntl.LOCK_UN)
					return

				# --- CQ-001: skip-erosion-after-refresh flag consumption ---
				if skip_next_erosion:
					logger.info(
						"CQ-001: skip_next_erosion flag active — skipping erosion this cycle to protect freshly-refreshed post-vacation engrams."
					)
					# Clear the flag; erosion resumes on the cycle after this one.
					self._write_metabolism_state(f, now, skip_next_erosion=False)
					if has_fcntl:
						fcntl.flock(f, fcntl.LOCK_UN)
					return

				# --- Normal cycle: update state and proceed to erosion ---
				self._write_metabolism_state(f, now, skip_next_erosion=False)
				if has_fcntl:
					fcntl.flock(f, fcntl.LOCK_UN)

		except OSError:
			pass

		for coll in cfg.METABOLISM_AUTO_COLLECTIONS:
			try:
				if cfg.METABOLISM_STRATEGY == "LAZY":
					self.purge_dead_memories(coll.strip())
				else:
					self.apply_erosion(coll.strip())
			except Exception as e:
				logger.error(f"Metabolism failed in {coll}: {e}")

	def purge_dead_memories(self, collection: str) -> None:
		"""
		The 'Gran Purge' (v5.6.0).
		Atomic deletion of extremely old engrams using Qdrant's filter-based delete.
		No scroll loop, O(1) database operation.
		"""
		timestamp_limite = time.time() - cfg.MAX_SINK_TIME

		try:
			self.client.delete(
				collection_name=collection,
				points_selector=models.FilterSelector(
					filter=models.Filter(
						must=[
							models.FieldCondition(key="last_recalled_at", range=models.Range(lt=timestamp_limite)),
							models.FieldCondition(key="immune", match=models.MatchValue(value=False)),
						]
					)
				),
			)
			logger.info(f"Gran Purge executed for '{collection}'. Engrams older than {cfg.MAX_SINK_TIME / 86400:.1f} days removed.")
		except Exception as e:
			logger.error(f"Gran Purge failed in {collection}: {e}")

	def _refresh_ttl_timestamps(self, collection: str) -> None:
		"""Absence Guard: forward all non-immune last_recalled_at to now.

		Called automatically when idle gap > ABSENCE_THRESHOLD.
		Prevents mass-deletion of the Bunker after long periods of inactivity
		(e.g. the system was powered off or the user was on vacation).
		"""
		now = time.time()
		offset = None
		refreshed = 0

		scroll_filter = models.Filter(must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))])

		match_count = 0
		while True:
			try:
				response = self.client.scroll(
					collection_name=collection, scroll_filter=scroll_filter, limit=200, offset=offset, with_payload=False, with_vectors=False
				)
			except Exception as e:
				logger.error(f"TTL refresh scroll failed: {_mask_pii_exception(e)}")
				break

			point_ids = [hit.id for hit in response[0]]
			if point_ids:
				try:
					self.client.set_payload(collection_name=collection, payload={"last_recalled_at": now}, points=point_ids)
					refreshed += len(point_ids)
				except Exception as e:
					logger.error(f"TTL refresh payload set failed: {_mask_pii_exception(e)}")

			offset = response[1]
			if offset is None:
				break

			# Safety break for unconfigured mocks in tests
			match_count += 1
			if match_count > cfg.ABSENCE_GUARD_SCROLL_LIMIT:
				logger.warning(f"Safety break triggered in TTL refresh for {collection}")
				break

		logger.info(f"Absence Guard: refreshed TTL for {refreshed} engrams in '{collection}'.")

	def _reinforce_points(self, collection: str, point_ids: List[str], increments: Dict[str, float]) -> List[PointUpdate]:
		"""Retrieves and updates reinforcement scores with thread-safety (Optimized Lock Scope)."""
		if not point_ids:
			return []

		valid_ids = []
		for pid in point_ids:
			if isinstance(pid, int):
				valid_ids.append(pid)
			else:
				try:
					uuid.UUID(str(pid))
					valid_ids.append(pid)
				except (ValueError, AttributeError):
					continue

		# 1. Retrieve points OUTSIDE the lock to avoid I/O serialization
		try:
			points = self.client.retrieve(collection_name=collection, ids=valid_ids, with_payload=True, with_vectors=False)
		except Exception as e:
			logger.error(f"Reinforcement retrieval failed: {_mask_pii_exception(e)}")
			return []

		updated_points: List[PointUpdate] = []
		update_operations = []

		# 2. Scope the lock only to the mathematical transition and payload preparation
		with self._reinforce_lock:
			for p in points:
				if p.payload is None:
					continue

				score = float(p.payload.get("reinforcement_score", 1.0))
				p_id_str = str(p.id)
				inc = increments.get(p_id_str, 0.0)

				new_score = min(score + inc, cfg.IMMUNITY_THRESHOLD)
				p.payload["reinforcement_score"] = round(new_score, 2)
				p.payload["last_recalled_at"] = time.time()

				if p.payload["reinforcement_score"] >= cfg.IMMUNITY_THRESHOLD:
					p.payload["immune"] = True

				updated_points.append(PointUpdate(id=p.id, payload=p.payload))
				# PERF-001: Prepare focused batch operations — only send the keys that changed.
				# Avoids re-transmitting large 'content' strings over the wire.
				focused_payload = {
					"reinforcement_score": p.payload["reinforcement_score"],
					"last_recalled_at": p.payload["last_recalled_at"],
				}
				if "immune" in p.payload:
					focused_payload["immune"] = p.payload["immune"]

				update_operations.append(
					models.SetPayloadOperation(set_payload=models.SetPayload(payload=focused_payload, points=[p.id]))  # type: ignore
				)

		# 3. Execute batch update OUTSIDE the lock (Qdrant handles its own internal locking/concurrency)
		if update_operations:
			try:
				self.client.batch_update_points(collection_name=collection, update_operations=update_operations)
			except Exception as e:
				logger.error(f"Reinforcement batch update failed: {_mask_pii_exception(e)}")
				return []

		return updated_points

	def search_and_reinforce(self, collection: str, query: str, limit: int = 3, deep_recall: bool = False) -> List[Any]:
		"""Semantic search followed by B760 synaptic reinforcement."""
		# CQ-003: Robust trigger detection for Deep Recall using word boundaries
		if not deep_recall:
			import re as regex_lib

			for phrase in cfg.DEEP_RECALL_TRIGGERS:
				pattern = rf"\b{regex_lib.escape(phrase)}\b"
				if regex_lib.search(pattern, query, regex_lib.IGNORECASE):
					deep_recall = True
					break

		vector = self._get_vector(query)

		search_filter = None
		if not deep_recall:
			search_filter = models.Filter(must=[models.FieldCondition(key="reinforcement_score", range=models.Range(gte=0.2))])

		try:
			results = self.client.query_points(
				collection_name=collection, query=vector, query_filter=search_filter, limit=limit, with_payload=True, with_vectors=False
			).points
		except Exception as e:
			logger.error(f"Query failed: {_mask_pii_exception(e)}")
			return []

		increment_map: Dict[str, float] = {}

		# v5.6.0: Lazy Metabolism Implementation
		# Recalculate decay for all results BEFORE reinforcement.
		# This ensures that we are reinforcing the 'true' decayed score.
		decayed_results = []
		update_operations = []

		for hit in results:
			if hit.payload is None:
				continue

			if cfg.METABOLISM_STRATEGY == "LAZY":
				original_score = float(hit.payload.get("reinforcement_score", 1.0))
				new_score = self._calculate_lazy_decay(hit.payload)

				if new_score <= 0:
					# This engram has conceptually 'died' in the gap.
					# We exclude it from results and mark it for deletion in Qdrant.
					try:
						self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[hit.id]))
					except Exception as e:
						logger.error(f"Lazy deletion failed: {e}")
					continue

				if new_score < original_score:
					hit.payload["reinforcement_score"] = new_score
					# We don't update 'last_recalled_at' yet, that happens in _reinforce_points
					# but we do want to sync the new score to Qdrant.
					update_operations.append(
						models.SetPayloadOperation(set_payload=models.SetPayload(payload={"reinforcement_score": new_score}, points=[hit.id]))
					)

			decayed_results.append(hit)
			increment_map[str(hit.id)] = cfg.REINFORCEMENT_INCREMENT

		if update_operations:
			try:
				self.client.batch_update_points(collection_name=collection, update_operations=update_operations)
			except Exception as e:
				logger.error(f"Lazy decay sync failed: {e}")

		# v5.6.0: N-hop Synaptic Propagation (Hebb's Law Expansion)
		# We use a breadth-first approach to propagate reinforcement through the graph.
		current_hop_ids = [str(hit.id) for hit in decayed_results]
		visited_ids = set(current_hop_ids)
		current_increment = cfg.REINFORCEMENT_INCREMENT * cfg.PROPAGATION_FACTOR

		for depth in range(1, cfg.PROPAGATION_DEPTH + 1):
			next_hop_ids = set()

			# For the first hop, we already have payloads in decayed_results
			if depth == 1:
				for hit in decayed_results:
					if hit.payload:
						assocs = hit.payload.get("associations", [])
						for a_id in assocs:
							a_id_str = str(a_id)
							increment_map[a_id_str] = increment_map.get(a_id_str, 0.0) + current_increment
							if a_id_str not in visited_ids:
								next_hop_ids.add(a_id_str)
			else:
				# Fetch payloads for the current ring to find the next one
				try:
					if current_hop_ids:
						points = self.client.retrieve(collection_name=collection, ids=current_hop_ids, with_payload=True, with_vectors=False)
						for p in points:
							if p.payload:
								assocs = p.payload.get("associations", [])
								for a_id in assocs:
									a_id_str = str(a_id)
									increment_map[a_id_str] = increment_map.get(a_id_str, 0.0) + current_increment
									if a_id_str not in visited_ids:
										next_hop_ids.add(a_id_str)
				except Exception as e:
					logger.error(f"N-hop retrieval failed at depth {depth}: {e}")
					break

			# 2. Cleanup and advance
			visited_ids.update(next_hop_ids)
			current_hop_ids = list(next_hop_ids)
			current_increment *= cfg.PROPAGATION_DECAY  # Diminishing returns (δ)

			# CF-005: Circuit Breaker for Hub Fan-out
			if len(increment_map) >= cfg.MAX_PROPAGATION_POINTS or not current_hop_ids:
				break

		if not increment_map:
			return decayed_results

		points_to_update = self._reinforce_points(collection, list(increment_map.keys()), increment_map)

		if points_to_update:
			update_map = {str(p.id): p.payload for p in points_to_update}
			for hit in decayed_results:
				hit_id_str = str(hit.id)
				if hit_id_str in update_map and hit.payload is not None:
					hit.payload.update(update_map[hit_id_str])


		return decayed_results

	def dream(self, collection: str, limit: int = 10) -> Dict[str, Any]:
		"""
		Sovereign Oneiromancy (v6.0).
		Autonomous synaptic discovery during idle Pulse cycles.
		Finds latent associations (axons) between random engrams.
		"""
		logger.info(f"Oneiromancy: Initiating dream sequence for '{collection}'...")
		
		# 1. Scroll for a set of 'active' engrams (not immune, fairly recent)
		try:
			response = self.client.scroll(
				collection_name=collection,
				scroll_filter=models.Filter(
					must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))]
				),
				limit=limit,
				with_payload=True,
				with_vectors=True
			)
		except Exception as e:
			logger.error(f"Dream scroll failed: {e}")
			return {"status": "error", "message": str(e)}

		points, _ = response
		if not points:
			return {"status": "empty", "message": "No non-immune memories to dream about."}

		synapses_created = 0

		for p in points:
			if not p.payload or p.vector is None:
				continue
			
			# 2. Semantic Search for potential partners
			try:
				vector = p.vector # type: ignore
				results = self.client.query_points(
					collection_name=collection,
					query=vector,
					limit=5,
					with_payload=True,
					query_filter=models.Filter(
						must_not=[models.HasIdCondition(has_id=[p.id])]
					)
				).points
			except Exception as e:
				logger.error(f"Dream search failed for {p.id}: {e}")
				continue

			for hit in results:
				if hit.score > 0.85: # High semantic overlap
					assocs = p.payload.get("associations", [])
					hit_id_str = str(hit.id)
					
					if hit_id_str not in assocs:
						# 3. Create Synapse (Axon)
						assocs.append(hit_id_str)
						# Cap associations using config
						if len(assocs) > cfg.MAX_AXONS:
							assocs = assocs[-cfg.MAX_AXONS:]
						
						try:
							self.client.set_payload(
								collection_name=collection,
								payload={"associations": assocs},
								points=[p.id]
							)
							synapses_created += 1
							logger.debug(f"Oneiromancy: Synapse formed [{p.id}] -> [{hit_id_str}] (Score: {hit.score:.2f})")
						except Exception as e:
							logger.error(f"Failed to set dream association: {e}")

		logger.info(f"Oneiromancy: Dream sequence complete. {synapses_created} synapses formed.")
		return {"status": "ok", "synapses": synapses_created}

	def _calculate_decay(self, current_score: float, rate: float) -> float:
		"""Computes decay based on the configured strategy."""
		if cfg.DECAY_STRATEGY == "exponential":
			new_score = current_score * (1.0 - rate)
			if round(new_score, 2) >= round(current_score, 2) and current_score > 0:
				new_score = current_score - 0.01
		else:
			new_score = current_score - rate

		return float(round(max(new_score, 0.0), 2))

	def _calculate_lazy_decay(self, payload: Dict[str, Any]) -> float:
		"""Calculates the current score of an engram based on time elapsed since last recall."""
		if payload.get("immune"):
			return float(payload.get("reinforcement_score", cfg.IMMUNITY_THRESHOLD))

		last_recalled = payload.get("last_recalled_at", time.time())
		score = float(payload.get("reinforcement_score", 1.0))
		gap = time.time() - last_recalled

		if gap < cfg.METABOLISM_COOLDOWN:
			return score

		cycles = gap / cfg.METABOLISM_COOLDOWN

		intensity = float(payload.get("intensity", 1.0))
		ep = payload.get("emotional_profile", [])
		emotions = [e["label"] for e in ep] if ep else [str(payload.get("emotion", cfg.DEFAULT_EMOTION))]

		multiplier = get_emotional_stability_multiplier(emotions, intensity)
		effective_rate = cfg.EROSION_RATE * multiplier

		# Apply decay for all missed cycles
		if cfg.DECAY_STRATEGY == "exponential":
			new_score = score * ((1.0 - effective_rate) ** cycles)
		else:
			new_score = score - (effective_rate * cycles)

		return float(round(max(new_score, 0.0), 2))

	def apply_erosion(self, collection: str, rate: Optional[float] = None) -> None:
		"""Decays non-immune memories; score <= 0 leads to deletion."""
		if rate is None:
			rate = cfg.EROSION_RATE

		if rate > 0.5:
			logger.warning(f"High erosion: {rate}")
		if rate <= 0:
			return

		offset = None
		eroded_count = 0
		deleted_count = 0

		# Calculate the TTL threshold: Only erode memories that haven't been recalled
		# recently. Wait at least METABOLISM_COOLDOWN before eroding again.
		ttl_threshold = time.time() - cfg.METABOLISM_COOLDOWN

		scroll_filter = models.Filter(
			must=[models.FieldCondition(key="last_recalled_at", range=models.Range(lt=ttl_threshold))],
			must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))],
		)

		iterations = 0
		while True:
			try:
				response = self.client.scroll(
					collection_name=collection, scroll_filter=scroll_filter, limit=100, offset=offset, with_payload=True, with_vectors=False
				)
			except Exception as e:
				logger.error(f"Erosion scroll failed: {_mask_pii_exception(e)}")
				break

			points_to_delete: List[Any] = []

			update_operations = []

			for hit in response[0]:
				if hit.payload is None:
					continue

				score = float(hit.payload.get("reinforcement_score", 1.0))
				if hit.payload.get("immune"):
					continue

				# Emotional Stability (v5.4.0 ACE Engine)
				intensity = float(hit.payload.get("intensity", 1.0))

				# Use full profile if available, else primary emotion
				ep = hit.payload.get("emotional_profile", [])
				emotions = [e["label"] for e in ep] if ep else [str(hit.payload.get("emotion", cfg.DEFAULT_EMOTION))]

				multiplier = get_emotional_stability_multiplier(emotions, intensity)

				effective_rate = (rate if rate is not None else cfg.EROSION_RATE) * multiplier
				new_score = self._calculate_decay(score, effective_rate)

				if new_score <= 0:
					points_to_delete.append(str(hit.id))
					deleted_count += 1
				else:
					eroded_count += 1
					hit.payload["reinforcement_score"] = new_score
					hit.payload["last_recalled_at"] = time.time()

					# PERF-001: Only send modified keys.
					focused_payload = {
						"reinforcement_score": hit.payload["reinforcement_score"],
						"last_recalled_at": hit.payload["last_recalled_at"],
					}

					update_operations.append(
						models.SetPayloadOperation(set_payload=models.SetPayload(payload=focused_payload, points=[hit.id]))  # type: ignore
					)

			if update_operations:
				try:
					self.client.batch_update_points(collection_name=collection, update_operations=update_operations)
				except Exception as e:
					logger.error(f"Erosion batch update failed: {_mask_pii_exception(e)}")

			if points_to_delete:
				try:
					self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=points_to_delete))
				except Exception as e:
					logger.error(f"Erosion deletion failed: {_mask_pii_exception(e)}")

			offset = response[1]
			if offset is None:
				break

			# Safety break for unconfigured mocks in tests
			iterations += 1
			if iterations > 1000:
				logger.warning(f"Safety break triggered in erosion for {collection}")
				break

		logger.info(f"Erosion complete. Updated: {eroded_count}, Deleted: {deleted_count}")

	def sanitize(self, collection: str, dry_run: bool = False) -> Dict[str, Any]:
		"""
		Sanitation Protocol:
		1. Deduplication: Removes engrams with exact same content.
		2. Schema Migration: Back-fills missing color/emotion/intensity from older versions.
		"""
		offset = None
		seen_content: Dict[str, str] = {}  # content -> id
		duplicates: List[Any] = []
		migrated_count = 0

		logger.info(f"Starting sanitation for {collection}...")
		iterations = 0
		while True:
			try:
				response = self.client.scroll(collection_name=collection, limit=100, offset=offset, with_payload=True, with_vectors=False)
			except Exception as e:
				logger.error(f"Sanitation scroll failed: {_mask_pii_exception(e)}")
				break

			update_operations = []

			for hit in response[0]:
				if hit.payload is None:
					continue

				content = str(hit.payload.get("content", ""))
				content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

				# 1. Deduplication Check
				if content_hash in seen_content:
					duplicates.append(str(hit.id))
					continue
				seen_content[content_hash] = str(hit.id)

				# 2. Schema Migration Check
				needs_migration = False
				update_payload: Dict[str, Any] = {}

				if "color" not in hit.payload:
					update_payload["color"] = cfg.DEFAULT_COLOR
					needs_migration = True
				if "emotion" not in hit.payload:
					update_payload["emotion"] = cfg.DEFAULT_EMOTION
					needs_migration = True
				if "intensity" not in hit.payload:
					update_payload["intensity"] = 1.0
					needs_migration = True
				if hit.payload.get("schema_version") != cfg.CURRENT_SCHEMA_VERSION:
					update_payload["schema_version"] = cfg.CURRENT_SCHEMA_VERSION
					needs_migration = True

				if needs_migration:
					migrated_count += 1
					if not dry_run:
						update_operations.append(models.SetPayloadOperation(set_payload=models.SetPayload(payload=update_payload, points=[hit.id])))  # type: ignore

			if update_operations and not dry_run:
				try:
					self.client.batch_update_points(collection_name=collection, update_operations=update_operations)
				except Exception as e:
					logger.error(f"Migration batch update failed: {_mask_pii_exception(e)}")

			offset = response[1]
			if offset is None:
				break

			# Safety break for unconfigured mocks in tests
			iterations += 1
			if iterations > 1000:
				logger.warning(f"Safety break triggered in sanitation for {collection}")
				break

		# Remove duplicates
		if duplicates and not dry_run:
			try:
				self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=duplicates))
			except Exception as e:
				logger.error(f"Duplicate deletion failed: {e}")

		return {"collection": collection, "duplicates_found": len(duplicates), "migrated_records": migrated_count, "dry_run": dry_run}

	def get_stats(self, collection: str) -> Dict[str, Any]:
		"""Returns collection diagnostics."""
		try:
			info = self.client.get_collection(collection_name=collection)
			return {
				"status": getattr(info, "status", "unknown"),
				"points_count": getattr(info, "points_count", 0),
				"segments_count": getattr(info, "segments_count", 0),
			}
		except Exception as e:
			logger.error(f"Stats failed: {e}")
			return {"status": "error", "points_count": 0, "segments_count": 0}
