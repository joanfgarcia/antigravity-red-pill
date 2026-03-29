import hashlib
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client.http import models

try:
	from fastembed import TextEmbedding
except ImportError:
	TextEmbedding = Any  # type: ignore

import red_pill.config as cfg
from red_pill.affect import get_memory_engine
from red_pill.events import MemoryAddedEvent, get_event_bus
from red_pill.hive import HiveMind
from red_pill.schemas import CreateEngramRequest, EngramPayload
from red_pill.utils.affect import (
	calculate_fsrs_initial_parameters,
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


class BayesianInferenceEngine:
	"""
	B-Utility Kernel: Beta Distribution Inferred Reliability.
	Calculates the expected utility E[theta] = alpha / (alpha + beta).
	Used for technical and directive collections.
	"""

	@staticmethod
	def calculate_utility(alpha: float, beta: float) -> float:
		"""Returns the expected value of the beta distribution."""
		if alpha <= 0 or beta <= 0:
			return 0.5
		return alpha / (alpha + beta)

	@staticmethod
	def normalize_to_reinforcement_score(utility: float) -> float:
		"""Maps utility [0, 1] to reinforcement_score [0, 10]."""
		return round(utility * 10.0, 2)

	@staticmethod
	def calculate_erosion(beta: float, time_passed_days: float, kappa: Optional[float] = None) -> float:
		"""Accumulates uncertainty (beta) based on elapsed time."""
		if kappa is None:
			kappa = cfg.BAYESIAN_STABILITY_KAPPA  # fallback for standalone use
		# MEM-001: Uncertainty grows linearly with time but is capped to prevent infinite compounding
		raw_beta = beta + (time_passed_days * kappa)
		max_beta = getattr(cfg, "BAYESIAN_MAX_BETA", 20.0)
		return min(raw_beta, max_beta)


class MemoryManager:
	"""B760-Adaptive memory engine."""

	def __init__(
		self,
		url: str = cfg.QDRANT_URL,
		config=None,
		hive=None,
	):
		self.cfg = config if config else cfg

		# Facade Pattern: Delegate to core engines
		from red_pill.core.embeddings import EmbeddingEngine
		from red_pill.core.metabolism import MetabolismKernel
		from red_pill.core.storage import StorageEngine

		self.storage = StorageEngine(url=url, config=self.cfg)
		self.client = self.storage.client  # Retained for direct access/backward compat
		self.embeddings = EmbeddingEngine(config=self.cfg)
		self.metabolism = MetabolismKernel(storage_engine=self.storage, config=self.cfg)

		self._reinforce_lock = threading.Lock()

		# HiveMind: injectable for Enterprise/Community (e.g. no-op, custom backend)
		self.hive = hive if hive is not None else HiveMind()

		# ---------------------------------------------------------------
		# Enterprise Extension Point: Protocolo Sueño hooks
		# Enterprise/Community modules register callbacks here at boot.
		# Callbacks signature: (summary: dict) -> None
		# The Foundation fires them after a sleep cycle completes.
		# ---------------------------------------------------------------
		self._sleep_hooks: List[Any] = []

	def register_sleep_hook(self, callback) -> None:
		"""
		Register a callback to be fired after each sleep/consolidation cycle.
		Enterprise uses this to upload the nightly synthesis to Cerberus.
		Community uses this to share anonymized learning summaries.

		callback(summary: dict) -> None
			summary keys: 'processed_count', 'collection', 'timestamp'
		"""
		self._sleep_hooks.append(callback)
		logger.debug(f"[DI] Registered sleep hook: {callback.__name__ if hasattr(callback, '__name__') else repr(callback)}")

	def fire_sleep_hooks(self, summary: dict) -> None:
		"""Called by perform_sleep_cycle (or Enterprise wrapper) after consolidation."""
		for hook in self._sleep_hooks:
			try:
				hook(summary)
			except Exception as e:
				logger.warning(f"[DI] Sleep hook {hook!r} raised an exception: {e}")

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
			# Trace logging to verify immunity flag persistence (P0 debugging)
			is_immune = payload.get("immune", "MISSING")
			logger.debug(f"[_parse_payload] Incoming payload immune flag: {is_immune}")

			validated = EngramPayload.model_validate(payload)

			logger.debug(f"[_parse_payload] Validated object immune flag: {validated.immune}")

			# Convert back to dict for Qdrant client compatibility downstream
			return validated.model_dump()
		except Exception as e:
			logger.warning(f"Payload strict validation failed (Original Sin detected). Returning raw payload. Error: {_mask_pii_exception(e)}")
			return payload

	def _ensure_collection(self, collection_name: str) -> None:
		self.storage.ensure_collection(collection_name)

	def _get_vector(self, text: str) -> List[float]:
		return self.embeddings.get_vector(text)

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
		recursion_depth: int = 0,
	) -> str:
		"""Stores a new engram with B760 validation and emotional chroma."""
		# v5.6.3: Synaptic Fragmentation (Anti-Amnesia Logic - Pre-validation)
		# If the text is a massive block, we split it into sinaptic fragments
		# before validation to support graceful degradation of oversized inputs.
		metadata = (metadata or {}).copy()
		if len(text) > self.cfg.CHUNK_THRESHOLD and not metadata.get("_is_fragment"):
			if recursion_depth >= 3:
				logger.warning("MEM-002: Max recursion depth (3) reached for engram fragmentation. Truncating.")
				text = text[: self.cfg.CHUNK_THRESHOLD]
			else:
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
						recursion_depth=recursion_depth + 1,
						intensity=intensity,
						force_immune=force_immune,
					)

			# Return the ID of the anchor point
			return parent_id

		# SEC-001 & SEC-008: Validation via Pydantic schema
		# SEC-001: Strip reserved keys before validation to ensure robustness
		for key in CreateEngramRequest.RESERVED_KEYS:
			metadata.pop(key, None)

		# v5.4.0: Temporal Pulse Detection
		pulse = record_interaction()
		metadata["pulse_status"] = pulse["status"]
		metadata["pulse_delta"] = pulse["delta_seconds"]

		# v5.4.0: Advanced Multi-Emotion Profile
		emotional_profile = []
		os_detect = os.getenv("EMOTION_AUTO_DETECT", "True").lower() == "true"
		if os_detect:
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

		try:
			validated_request = CreateEngramRequest(
				content=text,
				importance=importance,
				color=color,  # type: ignore
				emotion=emotion,  # type: ignore
				intensity=intensity,
				metadata=metadata,
				linguistic_markers=linguistic_markers,
			)
		except Exception as e:
			raise ValueError(f"Invalid engram data: {e}")

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

			# Phase B.1: Bayesian Utility Priors
			_is_bayesian = collection.strip() in self.cfg.BAYESIAN_COLLECTIONS
			if _is_bayesian:
				# Seed alpha from importance: higher importance = stronger initial belief
				_utility_alpha = max(1.0, importance)
				_utility_beta = 1.0
				_utility = BayesianInferenceEngine.calculate_utility(_utility_alpha, _utility_beta)
				_initial_score = BayesianInferenceEngine.normalize_to_reinforcement_score(_utility)
			else:
				_utility_alpha = 1.0
				_utility_beta = 1.0

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
				"utility_alpha": _utility_alpha,
				"utility_beta": _utility_beta,
				"linguistic_markers": validated_request.linguistic_markers,
				**clean_metadata,
			}

			self.client.upsert(collection_name=collection, points=[models.PointStruct(id=actual_id, vector=vector, payload=payload)])

			# Hive Mind Transmission (v5.0.0)
			if not force_immune and collection in ["work_memories", "social_memories"]:
				try:
					self.hive.transmit_experience(
						collection_name=f"hive_{collection}",
						content=text,
						vector=vector,
						metadata={"importance": importance, "agent_id": os.getenv("AGENT_ID", "standalone")},
					)
				except Exception as he:
					logger.warning(f"Hive transmission failed, but local memory retained: {he}")

			if self.cfg.METABOLISM_ENABLED:
				self._trigger_metabolism()

			# EventBus: notify Enterprise/Community layers
			get_event_bus().emit(
				MemoryAddedEvent(
					collection=collection,
					engram_id=actual_id,
					importance=importance,
					emotion=validated_request.emotion,
					color=validated_request.color,
				)
			)
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
		self.metabolism.trigger()

	def purge_dead_memories(self, collection: str) -> None:
		self.metabolism.purge_dead_memories(collection)

	def _reinforce_points(self, collection: str, point_ids: List[str], increments: Dict[str, float]) -> List[Any]:
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

		updated_points = []
		update_operations = []

		engine_type = self.cfg.MEMORY_ENGINES.get(collection.strip(), "fsrs_real")
		engine = get_memory_engine(engine_type)

		with self._reinforce_lock:
			for p in points:
				if p.payload is None or p.payload.get("immune"):
					continue

				# Ensure we have FSRS fields ready
				p.payload = self._parse_payload(p.payload, strict=True)

				p_id_str = str(p.id)
				inc = increments.get(p_id_str, self.cfg.REINFORCEMENT_INCREMENT)

				# Calculate reinforcement using the engine
				reinforced_updates = engine.calculate_reinforcement(p.payload, increment=inc)

				if reinforced_updates:
					p.payload.update(reinforced_updates)
					# Also explicitly bump the frequency timestamp
					p.payload["last_recalled_at"] = time.time()
					p.payload["recall_count"] = p.payload.get("recall_count", 0) + 1

					# Ensure updates are included for the batch operation
					reinforced_updates["last_recalled_at"] = p.payload["last_recalled_at"]
					reinforced_updates["recall_count"] = p.payload["recall_count"]

					updated_points.append(p)
					update_operations.append(
						models.SetPayloadOperation(set_payload=models.SetPayload(payload=reinforced_updates, points=[p.id]))  # type: ignore
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

			_is_permanent = collection.strip() in self.cfg.PERMANENT_COLLECTIONS
			if self.cfg.METABOLISM_STRATEGY == "LAZY" and not _is_permanent:
				# Phase 2: Pluggable Memory Engine
				engine_type = self.cfg.MEMORY_ENGINES.get(collection.strip(), "fsrs_real")
				engine = get_memory_engine(engine_type)

				# Execute engine
				decay_updates = engine.calculate_lazy_decay(hit.payload, current_time=time.time())

				if decay_updates.get("_delete"):
					logger.warning(f"Lazy decay DELETE ({engine_type}): engram {hit.id} in '{collection}' eroded below threshold. Removing.")
					try:
						self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[hit.id]))
					except Exception:
						pass
					continue

				if decay_updates:
					hit.payload.update(decay_updates)
					update_operations.append(
						models.SetPayloadOperation(
							set_payload=models.SetPayload(
								payload=decay_updates,
								points=[hit.id],
							)
						)
					)

			decayed_results.append(hit)
			increment_map[str(hit.id)] = self.cfg.REINFORCEMENT_INCREMENT

		if update_operations:
			try:
				# Apply grouped lazy decay batch update
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
		# PERF-01: Prevent O(N) sequential vector search blowup (Sound of Silence formatting)
		max_dreams = getattr(self.cfg, "MAX_DREAM_QUERIES", 10)
		if limit > max_dreams:
			logger.warning(f"Capping dream limit {limit} to MAX_DREAM_QUERIES ({max_dreams})")
			limit = max_dreams

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
							assocs = self._symmetric_axons_eviction(collection, assocs)
						try:
							self.client.set_payload(collection_name=collection, payload={"associations": assocs}, points=[p.id])
							synapses_created += 1
						except Exception as e:
							logger.debug(f"Dream association update failed: {e}")

		return {"status": "ok", "synapses": synapses_created}

	def _symmetric_axons_eviction(self, collection: str, assocs: List[Any]) -> List[Any]:
		"""
		ARCH-002: Hub-Aware Synaptic Pruning (Symmetric Eviction).
		Prevents the "Hub Problem" encountered in dense graph datasets by evaluating
		the absolute significance (reinforcement * importance) of the target node,
		instead of relying solely on edge age.
		"""
		import math

		if len(assocs) <= self.cfg.MAX_AXONS:
			return assocs

		try:
			assoc_ids = [a["id"] if isinstance(a, dict) else str(a) for a in assocs]
			records = self.client.retrieve(collection_name=collection, ids=assoc_ids, with_payload=["importance", "reinforcement_score"])

			hub_scores = {}
			for r in records:
				payload = r.payload or {}
				imp = max(0.1, float(payload.get("importance", 1.0)))
				reinf = max(0.1, float(payload.get("reinforcement_score", 1.0)))
				hub_scores[str(r.id)] = imp * reinf

			eviction_scores = {}
			for i, assoc in enumerate(assocs):
				a_id = assoc["id"] if isinstance(assoc, dict) else str(assoc)
				h_score = hub_scores.get(a_id, 0.1)  # 0.1 for missing nodes (dead links)
				# Age penalty: older items (lower index) get a tiny log penalty
				e_score = h_score * math.log(i + 2)
				eviction_scores[a_id] = e_score

			num_to_evict = len(assocs) - self.cfg.MAX_AXONS
			sorted_by_weakness = sorted(assocs, key=lambda x: eviction_scores[x["id"] if isinstance(x, dict) else str(x)])
			victim_ids = {v["id"] if isinstance(v, dict) else str(v) for v in sorted_by_weakness[:num_to_evict]}

			return [a for a in assocs if (a["id"] if isinstance(a, dict) else str(a)) not in victim_ids]

		except Exception as e:
			logger.warning(f"Symmetric eviction failed, falling back to chronological FIFO: {e}")
			return assocs[-self.cfg.MAX_AXONS :]

	def _calculate_decay(self, current_score: float, rate: float) -> float:
		if self.cfg.DECAY_STRATEGY.lower() == "exponential":
			new_score = current_score * (1.0 - rate)
			if round(new_score, 2) >= round(current_score, 2) and current_score > 0:
				new_score = current_score - 0.01
		else:
			new_score = current_score - rate
		return float(round(max(new_score, 0.0), 2))

	def _calculate_lazy_decay(self, payload: Dict[str, Any], collection: str) -> float:
		if payload.get("immune"):
			return float(payload.get("reinforcement_score", self.cfg.IMMUNITY_THRESHOLD))

		# Pluggable Engine Logic
		engine_type = self.cfg.MEMORY_ENGINES.get(collection.strip(), "fsrs_real")
		engine = get_memory_engine(engine_type)

		# We use the engine to calculate what the decay *would be* right now
		decay_updates = engine.calculate_lazy_decay(payload, current_time=time.time())

		if decay_updates.get("_delete"):
			return 0.0

		if "reinforcement_score" in decay_updates:
			return float(decay_updates["reinforcement_score"])

		return float(payload.get("reinforcement_score", 1.0))

	def apply_erosion(self, collection: str, rate: Optional[float] = None) -> None:
		self.metabolism.apply_erosion(collection, rate)

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

				# v6.1: Biological Refraction (Refract legacy monolithic Prompts/Responses)
				if content.startswith("USER: "):
					import re

					# Catch polymorphic responses from Swarm Agents even if newlines were stripped
					match = re.search(r"\b(ASSISTANT|TOOL|ORCHESTRATOR|MINION|SMITH|KEYMAKER|COMPRESSOR):\s(.*)", content, flags=re.DOTALL)
					if match:
						role = match.group(1)
						refracted_count += 1
						if not dry_run:
							try:
								importance = float(hit.payload.get("reinforcement_score", 1.0))
								color = hit.payload.get("color", self.cfg.DEFAULT_COLOR)
								emotion = hit.payload.get("emotion", self.cfg.DEFAULT_EMOTION)
								intensity = float(hit.payload.get("intensity", 1.0))
								immune = bool(hit.payload.get("immune", False))

								self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[hit.id]))

								p_text = content[: match.start()].replace("USER: ", "", 1).strip()
								r_text = match.group(2).strip()

								prev_id = None
								if p_text:
									prev_id = self.add_memory(
										collection,
										f"Operator Prompt: {p_text}",
										importance,
										color=color,
										emotion=emotion,
										intensity=intensity,
										force_immune=immune,
									)
								if r_text:
									node_prefix = "AI" if role == "ASSISTANT" else role.capitalize()
									r_id = self.add_memory(
										collection,
										f"{node_prefix} Response Node: {r_text}",
										importance,
										color=color,
										emotion=emotion,
										intensity=intensity,
										force_immune=immune,
									)
									if prev_id and r_id:
										self.client.set_payload(collection_name=collection, payload={"associations": [prev_id]}, points=[r_id])

								logger.info(f"Refracted polymorphic legacy engram ({role}): {str(hit.id)[:8]}...")
							except Exception as e:
								logger.error(f"Biological Refraction failed for {hit.id}: {e}")
						continue

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

	def purge_identity(self) -> None:
		"""
		PRIV-GDPR: Art. 17 Right to be Forgotten.
		Drops all local collections from Qdrant and wipes the local ~/.agent/ context.
		"""
		logger.warning("Initiating GDPR Article 17 Purge (Right to be Forgotten).")

		# 1. Drop Qdrant Collections
		from red_pill.config import METABOLISM_AUTO_COLLECTIONS

		for coll in METABOLISM_AUTO_COLLECTIONS:
			try:
				if self.client.collection_exists(coll):
					self.client.delete_collection(collection_name=coll)
					logger.info(f"Dropped collection: {coll}")
			except Exception as e:
				logger.error(f"Failed to drop collection {coll}: {e}")

		# 2. Wipe ~/.agent/
		agent_dir = os.path.expanduser("~/.agent")
		if os.path.exists(agent_dir):
			try:
				import shutil

				shutil.rmtree(agent_dir)
				logger.info(f"Wiped local agent directory: {agent_dir}")
			except Exception as e:
				logger.error(f"Failed to wipe {agent_dir}: {e}")

		# 3. Wipe generic metabolism state file
		metabolism_file = os.path.expanduser("~/.red_pill_metabolism")
		if os.path.exists(metabolism_file):
			try:
				os.remove(metabolism_file)
			except Exception as e:
				logger.error(f"Failed to wipe {metabolism_file}: {e}")

		logger.warning("Identity purge complete.")

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

	def inject_signal(self, name: str, intensity: float, signal_type: str, source: str) -> None:
		"""
		Injects a biological/somatic signal into the immune dashboard.
		These are fixed-hash engrams that overwrite themselves to avoid duplication.
		"""
		try:
			import hashlib
			import uuid
			from datetime import datetime, timezone

			from qdrant_client.http import models

			sig_hash = hashlib.sha256(name.encode("utf-8")).hexdigest()
			point_id = str(uuid.UUID(sig_hash[:32]))

			# Check for existing signal to apply Pain Escalation
			try:
				existing = self.client.retrieve(collection_name="signal_memories", ids=[point_id])
				if existing and len(existing) > 0 and existing[0].payload:
					current_intensity = existing[0].payload.get("intensity", intensity)
					if signal_type == "pain":
						# Physical pain escalating over time
						intensity = min(10.0, current_intensity + self.cfg.SIGNAL_PAIN_ESCALATION_RATE)
			except Exception:
				pass

			payload = {
				"content": f"[{signal_type.upper()}] {name}",
				"signal_type": signal_type,
				"signal_source": source,
				"intensity": intensity,
				"created_at": datetime.now(timezone.utc).isoformat(),
			}

			# Zero vector for purely semantic/flag signals
			vector = [0.0] * self.cfg.VECTOR_SIZE

			self.client.upsert(collection_name="signal_memories", points=[models.PointStruct(id=point_id, vector=vector, payload=payload)])
			logger.info(f"Injected signal '{name}' (Intensity: {intensity})")
		except Exception as e:
			logger.error(f"Failed to inject signal '{name}': {e}")

	def evaporate_signals(self, name: str) -> None:
		"""
		Evaporates a specific biological signal by name (curing the pain).
		"""
		try:
			import hashlib
			import uuid

			from qdrant_client.http import models

			sig_hash = hashlib.sha256(name.encode("utf-8")).hexdigest()
			point_id = str(uuid.UUID(sig_hash[:32]))

			self.client.delete(collection_name="signal_memories", points_selector=models.PointIdsList(points=[point_id]))
			logger.debug(f"Evaporated signal '{name}'")
		except Exception as e:
			logger.warning(f"Failed to evaporate signal '{name}': {e}")
