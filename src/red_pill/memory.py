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
from red_pill.schemas import CreateEngramRequest, EngramPayload
from red_pill.utils.affect import (
	calculate_fsrs_initial_parameters,
	calculate_fsrs_new_stability,
	calculate_fsrs_retrievability,
	get_emotional_stability_multiplier,
)
from red_pill.utils.emotion import get_chroma_for_emotion, get_emotion, get_emotions
from red_pill.utils.fragmentation import synaptic_split
from red_pill.utils.pulse import record_interaction

# Backward compatibility alias for tests
synaptic_split = synaptic_split

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

	def __init__(self, url: str = cfg.QDRANT_URL, config=None):
		self.cfg = config if config else cfg
		self.client = QdrantClient(url=url, api_key=self.cfg.QDRANT_API_KEY)
		self.encoder: Optional[TextEmbedding] = None
		self._reinforce_lock = threading.Lock()
		self._metabolism_thread: Optional[threading.Thread] = None
		self.hive = HiveMind()

	def _parse_payload(self, payload: Dict[str, Any], strict: bool = True) -> Dict[str, Any]:
		"""
		Phase O.2 & O.3: Pydantic Schema Migration.
		If strict=True, pipes payload through EngramPayload to enforce presence of fields
		and hydrate missing FSRS dimensions (difficulty/stability).
		If strict=False (Raw Read Mode), bypasses validation to allow emergency maintenance.
		"""
		if not payload:
			return payload
		if not strict:
			return payload
		try:
			validated = EngramPayload.model_validate(payload)
			# Convert back to dict for Qdrant client compatibility downstream
			return validated.model_dump()
		except Exception as e:
			logger.warning(f"Payload strict validation failed (Original Sin detected). Returning raw payload. Error: {_mask_pii_exception(e)}")
			return payload

	def _ensure_collection(self, collection_name: str) -> None:
		"""Create a collection if it does not exist with the standard B760 vector schema."""
		if not self.client.collection_exists(collection_name):
			self.client.create_collection(
				collection_name=collection_name,
				vectors_config=models.VectorParams(size=self.cfg.VECTOR_SIZE, distance=models.Distance.COSINE),
			)
			logger.info(f"Ghost Collection created: {collection_name}")

	def _get_vector_from_daemon(self, text: str) -> Optional[List[float]]:
		"""Retrieves embedding from the memory sidecar socket."""
		socket_path = self.cfg.DAEMON_SOCKET_PATH
		if not os.path.exists(socket_path):
			return None

		try:
			with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
				client.settimeout(2.0)
				client.connect(socket_path)

				# SEC-002 & SEC-004: Auth & Payload
				request = {"text": text, "api_key": self.cfg.SIDECAR_AUTH_KEY}
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

				providers = [self.cfg.EXECUTION_PROVIDER] if self.cfg.EXECUTION_PROVIDER else None
				self.encoder = TextEmbedding(model_name=self.cfg.EMBEDDING_MODEL, providers=providers)
			except ImportError:
				raise RuntimeError("FastEmbed library is missing. All semantic memory operations are blocked.")

		assert self.encoder is not None
		vectors = list(self.encoder.embed([text]))
		if not vectors:
			raise IndexError(f"Embedding model returned no vectors for text: {text[:50]}...")
		# v5.6.2: Explicit typing for Mypy compliance
		v_item: Any = vectors[0]
		if hasattr(v_item, "tolist"):
			return list(v_item.tolist())
		return list(v_item)

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
		# v5.6.3: Synaptic Fragmentation (Anti-Amnesia Logic - Pre-validation)
		# If the text is a massive block, we split it into sinaptic fragments
		# before validation to support graceful degradation of oversized inputs.
		metadata = (metadata or {}).copy()
		if len(text) > self.cfg.CHUNK_THRESHOLD and not metadata.get("_is_fragment"):
			fragments = synaptic_split(text)
			parent_id = point_id if point_id else str(uuid.uuid4())

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

		# SEC-001 & SEC-008: Validation via Pydantic schema
		# SEC-001: Strip reserved keys before validation to ensure robustness
		for key in CreateEngramRequest.RESERVED_KEYS:
			metadata.pop(key, None)

		try:
			req = CreateEngramRequest(
				content=text,
				importance=importance,
				color=color,  # type: ignore
				emotion=emotion,  # type: ignore
				intensity=intensity,
				metadata=metadata,
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
		metadata["pulse_status"] = pulse["status"]
		metadata["pulse_delta"] = pulse["delta_seconds"]

		# v5.4.0: Advanced Multi-Emotion Profile
		emotional_profile = []
		if os_detect := os.getenv("EMOTION_AUTO_DETECT", "True").lower() == "true":
			if self.cfg.MULTI_EMOTION_INFERENCE:
				emotional_profile = get_emotions(text)

			if emotional_profile and emotion == self.cfg.DEFAULT_EMOTION:
				emotion = emotional_profile[0]["label"]
				if color == self.cfg.DEFAULT_COLOR:
					color = get_chroma_for_emotion(emotion)
			elif os_detect and emotion == self.cfg.DEFAULT_EMOTION:
				# Fallback to single if multi is disabled but detect is on
				detected = get_emotion(text)
				if detected:
					emotion = detected
					if color == self.cfg.DEFAULT_COLOR:
						color = get_chroma_for_emotion(emotion)

		if emotional_profile:
			metadata["emotional_profile"] = emotional_profile

		# v6.0: Automated Linguistic Marker Extraction (Claude-Pistis)
		import re

		markers = set()
		# 1. Quoted terms: "term"
		markers.update(re.findall(r"\"([^\"]+)\"", text))
		# 2. Keywords
		keywords = ["Aleth", "Bünker", "770", "enter-pánico", "PAAAAARAAAAAA", "engrama", "skin", "Titanium", "Joan"]
		for kw in keywords:
			if kw.lower() in text.lower():
				markers.add(kw)
		# 3. All-caps shouting (3+ chars)
		markers.update(re.findall(r"\b[A-Z]{3,}\b", text))
		linguistic_markers = list(markers)

		validated_request = CreateEngramRequest(
			content=text,
			importance=importance,
			color=color,  # type: ignore
			emotion=emotion,  # type: ignore
			intensity=intensity,
			metadata=metadata,
			linguistic_markers=linguistic_markers,
		)

		text = validated_request.content
		importance = validated_request.importance
		clean_metadata = validated_request.metadata

		actual_id = point_id if point_id else str(uuid.uuid4())
		try:
			vector = self._get_vector(text)

			for key in CreateEngramRequest.RESERVED_KEYS:
				clean_metadata.pop(key, None)

			# Emotional Seed Score (B760-Native Emotional Seed Scoring, v4.2.1)
			_emotion = validated_request.emotion
			_intensity = validated_request.intensity
			_color = validated_request.color
			if _emotion != "neutral" and _intensity > 1.0:
				_color_mult = self.cfg.EMOTIONAL_DECAY_MULTIPLIERS.get(_color, 1.0)
				_bonus = (_intensity / 10.0) * _color_mult * self.cfg.EMOTIONAL_SEED_FACTOR
				_initial_score = importance * (1.0 + _bonus)
			else:
				_initial_score = importance
			_initial_score = round(min(_initial_score, self.cfg.IMMUNITY_THRESHOLD * 0.9), 2)

			if force_immune:
				_initial_score = self.cfg.IMMUNITY_THRESHOLD

			# Phase O.5: FSRS Initialization
			emotions = [e["label"] for e in emotional_profile] if emotional_profile else [validated_request.emotion]
			fsrs_diff, fsrs_stab = calculate_fsrs_initial_parameters(emotions, validated_request.intensity)

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
				"schema_version": self.cfg.CURRENT_SCHEMA_VERSION,
				"difficulty": fsrs_diff,
				"stability": fsrs_stab,
				"linguistic_markers": validated_request.linguistic_markers,
				**clean_metadata,
			}

			self.client.upsert(collection_name=collection, points=[models.PointStruct(id=actual_id, vector=vector, payload=payload)])

			# Hive Mind Transmission (v5.0.0)
			if not force_immune and collection in ["work_memories", "social_memories"]:
				self.hive.transmit_experience(
					collection_name=f"hive_{collection}",
					content=text,
					vector=vector,
					metadata={"importance": importance, "agent_id": os.getenv("AGENT_ID", "standalone")},
				)

			if self.cfg.METABOLISM_ENABLED:
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
		"""Internal metabolism loop with cooldown check."""
		state_file = self.cfg.METABOLISM_STATE_FILE
		now = time.time()

		try:
			from filelock import FileLock, Timeout

			lock = FileLock(state_file + ".lock", timeout=0)
			with lock:
				with open(state_file, "a+") as f:
					last_run, skip_next_erosion = self._read_metabolism_state(f)
					gap = now - last_run if last_run > 0 else float("inf")

					# --- Cooldown gate ---
					if last_run > 0 and gap < self.cfg.METABOLISM_COOLDOWN:
						return

					# --- Absence guard ---
					abs_gap = now - last_run if last_run > 0 else 0
					if abs_gap > self.cfg.ABSENCE_THRESHOLD:
						logger.warning(
							f"Absence detected ({round(abs_gap / 86400, 1)} days). Running TTL refresh to protect the Bunker. Erosion skipped for this cycle and the next."
						)
						for coll in self.cfg.METABOLISM_AUTO_COLLECTIONS:
							try:
								self._refresh_ttl_timestamps(coll.strip())
							except Exception as e:
								logger.error(f"TTL refresh failed during absence recovery for {coll}: {e}")

						self._write_metabolism_state(f, now, skip_next_erosion=True)
						logger.info("Absence Guard triggered: Bunker refreshed and erosion short-circuited for this cycle.")
						return

					# --- CQ-001: skip-erosion-after-refresh flag consumption ---
					if skip_next_erosion:
						logger.info(
							"CQ-001: skip_next_erosion flag active — skipping erosion this cycle to protect freshly-refreshed post-vacation engrams."
						)
						self._write_metabolism_state(f, now, skip_next_erosion=False)
						return

					# --- Normal cycle: update state and proceed to erosion ---
					self._write_metabolism_state(f, now, skip_next_erosion=False)

		except Timeout:
			# Lock could not be acquired because another instance is running
			return
		except OSError:
			pass

		for coll in self.cfg.METABOLISM_AUTO_COLLECTIONS:
			try:
				if self.cfg.METABOLISM_STRATEGY == "LAZY":
					self.purge_dead_memories(coll.strip())
				else:
					self.apply_erosion(coll.strip())
			except Exception as e:
				logger.error(f"Metabolism failed in {coll}: {e}")

	def purge_dead_memories(self, collection: str) -> None:
		"""Atomic deletion of extremely old engrams."""
		timestamp_limite = time.time() - self.cfg.MAX_SINK_TIME

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
			logger.info(f"Gran Purge executed for '{collection}'.")
		except Exception as e:
			logger.error(f"Gran Purge failed in {collection}: {e}")

	def _refresh_ttl_timestamps(self, collection: str) -> None:
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

			match_count += 1
			if match_count > self.cfg.ABSENCE_GUARD_SCROLL_LIMIT:
				break

		logger.info(f"Absence Guard: refreshed TTL for {refreshed} engrams in '{collection}'.")

	def _reinforce_points(self, collection: str, point_ids: List[str], increments: Dict[str, float]) -> List[PointUpdate]:
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

		try:
			points = self.client.retrieve(collection_name=collection, ids=valid_ids, with_payload=True, with_vectors=False)
		except Exception as e:
			logger.error(f"Reinforcement retrieval failed: {_mask_pii_exception(e)}")
			return []

		updated_points: List[PointUpdate] = []
		update_operations = []

		with self._reinforce_lock:
			for p in points:
				if p.payload is None:
					continue

				# Ensure we have FSRS fields ready
				p.payload = self._parse_payload(p.payload, strict=True)

				score = float(p.payload.get("reinforcement_score", 1.0))
				stability = float(p.payload.get("stability", 1.0))
				difficulty = float(p.payload.get("difficulty", 5.0))
				last_recalled = float(p.payload.get("last_recalled_at", time.time()))

				p_id_str = str(p.id)

				# We use the propagation increment as a proxy for the 'success' weight of the recall event.
				inc = increments.get(p_id_str, 0.0)
				time_passed = time.time() - last_recalled

				# 1. Calculate retrievability prior to this reinforcement
				retrievability = calculate_fsrs_retrievability(stability, time_passed)

				# 2. Calculate newly boosted FSRS stability (a direct hit is a success)
				is_success = inc >= (self.cfg.REINFORCEMENT_INCREMENT * 0.5)
				new_stability = calculate_fsrs_new_stability(stability, difficulty, retrievability, is_success=is_success)

				# 3. Translate stability back into the legacy reinforcement_score scaler for backwards compatibility with UI/immunity
				# A stability of ~30 days translates to 10.0 (immunity)
				new_score = min(max(new_stability / 3.0, score + inc), self.cfg.IMMUNITY_THRESHOLD)

				p.payload["reinforcement_score"] = round(new_score, 2)
				p.payload["stability"] = round(new_stability, 3)
				p.payload["last_recalled_at"] = time.time()

				if p.payload["reinforcement_score"] >= self.cfg.IMMUNITY_THRESHOLD:
					p.payload["immune"] = True

				updated_points.append(PointUpdate(id=p.id, payload=p.payload))
				focused_payload = {
					"reinforcement_score": p.payload["reinforcement_score"],
					"stability": p.payload["stability"],
					"last_recalled_at": p.payload["last_recalled_at"],
				}
				if "immune" in p.payload:
					focused_payload["immune"] = p.payload["immune"]

				update_operations.append(
					models.SetPayloadOperation(set_payload=models.SetPayload(payload=focused_payload, points=[p.id]))  # type: ignore
				)

		if update_operations:
			try:
				self.client.batch_update_points(collection_name=collection, update_operations=update_operations)
			except Exception as e:
				logger.error(f"Reinforcement batch update failed: {_mask_pii_exception(e)}")
				return []

		return updated_points

	def record_interaction_pair(self, prompt: str, response: str, role: str = "assistant") -> str:
		"""
		Lazarus Phase 1: Encoding (Fast Memory Buffer).
		Saves raw interaction history directly into the `interaction_memories` collection.
		This bypasses traditional FSRS math as it is assumed to be short-term 'noise'
		until the Sleep (Consolidation) cycle distills it.
		"""
		collection = "interaction_memories"
		uid = str(uuid.uuid4())
		timestamp = int(time.time())

		# Structure the payload simply for the raw buffer
		text = f"USER: {prompt}\n\n{role.upper()}: {response}"
		payload = {
			"content": text,
			"importance": 5.0,  # Neutral baseline
			"timestamp": timestamp,
			"last_recalled_at": timestamp,
			"recall_count": 0,
			"associations": [],
			"associated_weight": 0.0,
			"color": "gray",  # Unprocessed color
			"difficulty": 5.0,  # Default FSRS D
			"stability": 2.0,  # Default FSRS S (Low stability for volatile memory)
			"metadata": {"type": "raw_interaction", "role": role},
		}

		vector = self._get_vector(text)

		try:
			self._ensure_collection(collection)
			self.client.upsert(
				collection_name=collection,
				points=[
					models.PointStruct(
						id=uid,
						payload=payload,
						vector=vector,
					)
				],
			)
			logger.debug(f"[ENCODING] Interaction recorded in fast buffer: {uid}")
			return uid
		except Exception as e:
			logger.error(f"Failed to record interaction pair: {e}")
			return ""

	def search_and_reinforce(self, collection: str, query: str, limit: int = 3, deep_recall: bool = False, strict: bool = True) -> List[Any]:
		if not deep_recall:
			import re as regex_lib

			for phrase in self.cfg.DEEP_RECALL_TRIGGERS:
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
		decayed_results = []
		update_operations = []

		for hit in results:
			if hit.payload is None:
				continue

			hit.payload = self._parse_payload(hit.payload, strict=strict)

			if self.cfg.METABOLISM_STRATEGY == "LAZY":
				score = float(hit.payload.get("reinforcement_score", 1.0))
				stability = float(hit.payload.get("stability", 1.0))
				last_recalled = float(hit.payload.get("last_recalled_at", time.time()))

				# Phase O.6: FSRS Lazy Erosion
				time_passed = time.time() - last_recalled
				retrievability = calculate_fsrs_retrievability(stability, time_passed)
				new_score = round(score * retrievability, 2)

				if new_score <= 0.05:
					try:
						self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[hit.id]))
					except Exception:
						pass
					continue

				if new_score < score:
					hit.payload["reinforcement_score"] = new_score
					update_operations.append(
						models.SetPayloadOperation(set_payload=models.SetPayload(payload={"reinforcement_score": new_score}, points=[hit.id]))
					)

			decayed_results.append(hit)
			increment_map[str(hit.id)] = self.cfg.REINFORCEMENT_INCREMENT

		if update_operations:
			try:
				self.client.batch_update_points(collection_name=collection, update_operations=update_operations)
			except Exception:
				pass

		current_hop_ids = [str(hit.id) for hit in decayed_results]
		visited_ids = set(current_hop_ids)
		current_increment = self.cfg.REINFORCEMENT_INCREMENT * self.cfg.PROPAGATION_FACTOR

		for depth in range(1, self.cfg.PROPAGATION_DEPTH + 1):
			next_hop_ids = set()
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
				except Exception:
					break

			visited_ids.update(next_hop_ids)
			current_hop_ids = list(next_hop_ids)
			current_increment *= self.cfg.PROPAGATION_DECAY
			if len(increment_map) >= self.cfg.MAX_PROPAGATION_POINTS or not current_hop_ids:
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

		# --- v6.0: Sovereign Evocative Cascade (Hybrid Vector-Graph) ---
		MAX_EVOKED = 3
		evoked_ids: set[str] = set()
		visited_ids = set(str(h.id) for h in decayed_results)

		# 1. Harvest `a_ids` (synapses forged organically by Sovereign Oneiromancy)
		for hit in decayed_results:
			if hit.payload:
				for a_id in hit.payload.get("associations", []):
					str_id = str(a_id)
					if str_id not in visited_ids and len(evoked_ids) < MAX_EVOKED:
						evoked_ids.add(str_id)
						visited_ids.add(str_id)

		cascade_results = []
		if evoked_ids:
			try:
				# 2. Ephemeral Fetch (Pulling the actual memories into context)
				points = self.client.retrieve(collection_name=collection, ids=list(evoked_ids), with_payload=True, with_vectors=False)
				for p in points:
					if p.payload:
						# Mark it as evoked for LLM context/parsing
						p.payload["_is_evoked"] = True
						cascade_results.append(p)
			except Exception as e:
				logger.error(f"Evocative Cascade lookup failed: {e}")

		# 3. Unified Stream (Direct Hits + Branching Memories)
		return decayed_results + cascade_results

	def dream(self, collection: str, limit: int = 10) -> Dict[str, Any]:
		logger.info(f"Oneiromancy: Dream sequence for '{collection}'...")
		try:
			response = self.client.scroll(
				collection_name=collection,
				scroll_filter=models.Filter(must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))]),
				limit=limit,
				with_payload=True,
				with_vectors=True,
			)
		except Exception as e:
			return {"status": "error", "message": str(e)}

		points, _ = response
		if not points:
			return {"status": "empty", "message": "No non-immune memories."}

		synapses_created = 0
		for p in points:
			if not p.payload or p.vector is None:
				continue
			try:
				from typing import cast

				results = self.client.query_points(
					collection_name=collection,
					query=cast(list[float], list(p.vector)) if p.vector is not None else [0.0],
					limit=5,
					with_payload=True,
					query_filter=models.Filter(must_not=[models.HasIdCondition(has_id=[p.id])]),
				).points
			except Exception:
				continue

			for hit in results:
				if hit.score > 0.85:
					assocs = p.payload.get("associations", [])
					hit_id_str = str(hit.id)
					if hit_id_str not in assocs:
						assocs.append(hit_id_str)
						if len(assocs) > self.cfg.MAX_AXONS:
							assocs = assocs[-self.cfg.MAX_AXONS :]
						try:
							self.client.set_payload(collection_name=collection, payload={"associations": assocs}, points=[p.id])
							synapses_created += 1
						except Exception as e:
							logger.debug(f"Dream association update failed: {e}")

		return {"status": "ok", "synapses": synapses_created}

	def _calculate_decay(self, current_score: float, rate: float) -> float:
		if self.cfg.DECAY_STRATEGY.lower() == "exponential":
			new_score = current_score * (1.0 - rate)
			if round(new_score, 2) >= round(current_score, 2) and current_score > 0:
				new_score = current_score - 0.01
		else:
			new_score = current_score - rate
		return float(round(max(new_score, 0.0), 2))

	def _calculate_lazy_decay(self, payload: Dict[str, Any]) -> float:
		if payload.get("immune"):
			return float(payload.get("reinforcement_score", self.cfg.IMMUNITY_THRESHOLD))
		last_recalled = payload.get("last_recalled_at", time.time())
		score = float(payload.get("reinforcement_score", 1.0))
		gap = time.time() - last_recalled
		if gap < self.cfg.METABOLISM_COOLDOWN:
			return score
		cycles = gap / self.cfg.METABOLISM_COOLDOWN
		intensity = float(payload.get("intensity", 1.0))
		ep = payload.get("emotional_profile", [])
		emotions = [e["label"] for e in ep] if ep else [str(payload.get("emotion", self.cfg.DEFAULT_EMOTION))]
		multiplier = get_emotional_stability_multiplier(emotions, intensity)
		effective_rate = self.cfg.EROSION_RATE * multiplier
		if self.cfg.DECAY_STRATEGY.lower() == "exponential":
			new_score = score * ((1.0 - effective_rate) ** cycles)
		else:
			new_score = score - (effective_rate * cycles)
		return float(round(max(new_score, 0.0), 2))

	def apply_erosion(self, collection: str, rate: Optional[float] = None) -> None:
		if rate is None:
			rate = self.cfg.EROSION_RATE
		if rate <= 0:
			return
		if rate > 0.5:
			logger.warning(f"High erosion rate detected ({rate}). Significant memory loss imminent.")
		offset = None
		eroded_count = 0
		deleted_count = 0
		ttl_threshold = time.time() - self.cfg.METABOLISM_COOLDOWN
		scroll_filter = models.Filter(
			must=[models.FieldCondition(key="last_recalled_at", range=models.Range(lt=ttl_threshold))],
			must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))],
		)
		match_count = 0
		while True:
			match_count += 1
			if match_count > 1000:  # Safety break
				break
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
				if hit.payload is None or hit.payload.get("immune"):
					continue

				# Sanitize check - ensure we have FSRS fields (Fallback if migration wasn't run)
				hit.payload = self._parse_payload(hit.payload, strict=True)

				score = float(hit.payload.get("reinforcement_score", 1.0))
				stability = float(hit.payload.get("stability", 1.0))  # Fallback
				last_recalled = float(hit.payload.get("last_recalled_at", time.time()))

				time_passed = time.time() - last_recalled

				# Phase O.6: FSRS Active Erosion
				# Calculate raw objective retrievability R on [0, 1] curve
				retrievability = calculate_fsrs_retrievability(stability, time_passed)

				# The reinforcement_score becomes a proxy for R scaled to [0, 10]
				new_score = round(score * retrievability, 2)

				if new_score <= 0.05:  # Cleaned up death threshold
					points_to_delete.append(str(hit.id))
					deleted_count += 1
				else:
					eroded_count += 1
					update_operations.append(
						models.SetPayloadOperation(
							set_payload=models.SetPayload(
								payload={"reinforcement_score": new_score, "last_recalled_at": time.time()}, points=[hit.id]
							)
						)
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
					logger.error(f"Erosion delete failed: {_mask_pii_exception(e)}")
			offset = response[1]
			if offset is None:
				break
		logger.info(f"Erosion complete in {collection}. Updated: {eroded_count}, Deleted: {deleted_count}")

	def sanitize(self, collection: str, dry_run: bool = False, strict: bool = True) -> Dict[str, Any]:
		"""Sanitizes a collection: removes duplicates, heals schemas, and refracts oversized legacy engrams."""
		offset = None
		seen_content: Dict[str, str] = {}
		duplicates: List[Any] = []
		migrated_count = 0
		refracted_count = 0
		match_count = 0
		while True:
			match_count += 1
			if match_count > 1000:  # Safety break
				break
			try:
				response = self.client.scroll(collection_name=collection, limit=100, offset=offset, with_payload=True, with_vectors=False)
			except Exception as e:
				logger.error(f"Sanitize scroll failed: {_mask_pii_exception(e)}")
				break
			update_operations = []
			for hit in response[0]:
				if hit.payload is None:
					continue
				content = str(hit.payload.get("content", ""))
				content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
				if content_hash in seen_content:
					duplicates.append(str(hit.id))
					continue
				seen_content[content_hash] = str(hit.id)

				# v5.6.3: Fragmentation Guard (Refract oversized legacy engrams)
				# If an engram exceeds the current high-purity limits (e.g. leftovers from v5.6.2),
				# we delete and re-add it to trigger the synaptic_split logic.
				if len(content) > self.cfg.CHUNK_THRESHOLD:
					refracted_count += 1
					if not dry_run:
						try:
							# Extract core metadata for re-entry
							importance = float(hit.payload.get("reinforcement_score", 1.0))
							color = hit.payload.get("color", self.cfg.DEFAULT_COLOR)
							emotion = hit.payload.get("emotion", self.cfg.DEFAULT_EMOTION)
							intensity = float(hit.payload.get("intensity", 1.0))
							immune = bool(hit.payload.get("immune", False))

							# Delete original
							self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[hit.id]))

							# Re-add (will trigger chunking automatically)
							self.add_memory(
								collection=collection,
								text=content,
								importance=importance,
								color=color,
								emotion=emotion,
								intensity=intensity,
								force_immune=immune,
							)
							logger.info(f"Refracted oversized legacy engram: {str(hit.id)[:8]}...")
						except Exception as e:
							logger.error(f"Fragmentation Guard failed for {hit.id}: {e}")
					continue

				update_payload = self._parse_payload(hit.payload, strict=strict)
				needs_migration = update_payload != hit.payload

				if needs_migration:
					migrated_count += 1
					if not dry_run:
						update_operations.append(models.SetPayloadOperation(set_payload=models.SetPayload(payload=update_payload, points=[hit.id])))
			if update_operations and not dry_run:
				try:
					self.client.batch_update_points(collection_name=collection, update_operations=update_operations)
				except Exception as e:
					logger.error(f"Sanitize migration failed: {_mask_pii_exception(e)}")
			offset = response[1]
			if offset is None:
				break
		if duplicates and not dry_run:
			try:
				self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=duplicates))
			except Exception as e:
				logger.error(f"Sanitize duplicate deletion failed: {_mask_pii_exception(e)}")
		return {
			"collection": collection,
			"duplicates_found": len(duplicates),
			"migrated_records": migrated_count,
			"refracted_records": refracted_count,
			"dry_run": dry_run,
		}

	def get_stats(self, collection: str) -> Dict[str, Any]:
		try:
			info = self.client.get_collection(collection_name=collection)
			return {
				"status": getattr(info, "status", "unknown"),
				"points_count": getattr(info, "points_count", 0),
				"segments_count": getattr(info, "segments_count", 0),
			}
		except Exception as e:
			logger.error(f"Failed to get collection stats: {_mask_pii_exception(e)}")
			return {"status": "error", "error": str(e), "points_count": 0, "segments_count": 0}

	def create_bunker_snapshot(self, collections: Optional[List[str]] = None) -> Dict[str, str]:
		"""
		Creates a full backup snapshot of the specified collections.
		If collections is None, uses all METABOLISM_AUTO_COLLECTIONS.
		Returns a dict mapping collection names to snapshot names.
		"""
		if collections is None:
			collections = self.cfg.METABOLISM_AUTO_COLLECTIONS

		snapshots_created = {}
		for coll in collections:
			coll = coll.strip()
			if not self.client.collection_exists(coll):
				logger.warning(f"Cannot create snapshot for non-existent collection: {coll}")
				continue
			try:
				logger.info(f"Creating snapshot for collection: {coll}...")
				snapshot_desc = self.client.create_snapshot(collection_name=coll)
				# snapshot_desc is a SnapshotDescription object with 'name', 'creation_time', 'size'
				if snapshot_desc:  # Add truthiness check
					snapshots_created[coll] = snapshot_desc.name
					logger.info(f"Snapshot created successfully: {snapshot_desc.name}")
				else:
					logger.error(f"Snapshot creation returned an empty descriptor for {coll}")
					snapshots_created[coll] = "ERROR: Empty snapshot descriptor"
			except Exception as e:
				logger.error(f"Failed to create snapshot for {coll}: {_mask_pii_exception(e)}")
				snapshots_created[coll] = f"ERROR: {str(e)}"

		return snapshots_created
