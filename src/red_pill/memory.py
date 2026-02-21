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

import red_pill.config as cfg
from red_pill.schemas import CreateEngramRequest

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
		self.encoder = None
		self._reinforce_lock = threading.Lock()
		self._initialize_encoder()

	def _initialize_encoder(self) -> None:
		"""Lazy-load gate for the local encoder."""
		pass

	def _get_vector_from_daemon(self, text: str) -> Optional[List[float]]:
		"""Retrieves embedding from the memory sidecar socket."""
		socket_path = cfg.DAEMON_SOCKET_PATH
		if not os.path.exists(socket_path):
			return None

		try:
			with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
				client.settimeout(0.5)
				client.connect(socket_path)
				request = {"text": text}
				client.sendall(json.dumps(request).encode('utf-8'))
				response_data = client.recv(1024 * 1024)
				if response_data:
					response = json.loads(response_data.decode('utf-8'))
					if response.get("status") == "ok":
						return response.get("vector")
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
				return [0.0] * cfg.VECTOR_SIZE

		return list(self.encoder.embed([text]))[0].tolist()

	def add_memory(self, collection: str, text: str, importance: float = 1.0, metadata: Optional[Dict[str, Any]] = None, point_id: Optional[str] = None, color: str = cfg.DEFAULT_COLOR, emotion: str = cfg.DEFAULT_EMOTION, intensity: float = 1.0) -> str:
		"""Stores a new engram with B760 validation and emotional chroma."""
		if metadata is None:
			metadata = {}

		# Handle 'immune' and reserved keys bypass for seeding
		force_immune = metadata.pop("immune", False)
		importance = metadata.pop("importance", importance)

		try:
			metadata = json.loads(json.dumps(metadata))
		except (TypeError, ValueError) as e:
			raise ValueError(f"Invalid metadata: {e}")

		validated_request = CreateEngramRequest(
			content=text,
			importance=importance,
			color=color,
			emotion=emotion,
			intensity=intensity,
			metadata=metadata
		)

		text = validated_request.content
		importance = validated_request.importance
		clean_metadata = validated_request.metadata

		actual_id = point_id if point_id else str(uuid.uuid4())
		vector = self._get_vector(text)

		for key in CreateEngramRequest.RESERVED_KEYS:
			clean_metadata.pop(key, None)

		# Emotional Seed Score (interim FSRS bridge, v4.2.1)
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
			**clean_metadata
		}

		try:
			self.client.upsert(
				collection_name=collection,
				points=[
					models.PointStruct(
						id=actual_id,
						vector=vector,
						payload=payload
					)
				]
			)
			if cfg.METABOLISM_ENABLED:
				self._trigger_metabolism()
			return actual_id
		except Exception as e:
			logger.error(f"Failed to add memory: {_mask_pii_exception(e)}")
			return ""

	def _trigger_metabolism(self) -> None:
		"""Background process to check and execute erosion."""
		try:
			thread = threading.Thread(target=self._run_metabolism_cycle, daemon=True)
			thread.start()
		except Exception as e:
			logger.error(f"Metabolism thread failed: {e}")

	def _run_metabolism_cycle(self) -> None:
		"""Internal metabolism loop with cooldown check."""
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

				f.seek(0)
				content = f.read().strip()
				if content:
					try:
						last_run = float(content)
						gap = now - last_run
						if gap < cfg.METABOLISM_COOLDOWN:
							if has_fcntl:
								fcntl.flock(f, fcntl.LOCK_UN)
							return
						# Absence guard: if idle > 7 days, refresh timestamps before eroding
						if gap > cfg.ABSENCE_THRESHOLD:
							logger.warning(
								f"Absence detected ({gap/86400:.1f} days). "
								"Running TTL refresh before erosion to protect the Bunker."
							)
							for coll in cfg.METABOLISM_AUTO_COLLECTIONS:
								try:
									self._refresh_ttl_timestamps(coll.strip())
								except Exception as e:
									logger.error(f"TTL refresh failed for {coll}: {e}")
					except ValueError:
						pass

				f.seek(0)
				f.truncate()
				f.write(str(now))
				f.flush()
				if has_fcntl:
					fcntl.flock(f, fcntl.LOCK_UN)
		except OSError:
			pass

		for coll in cfg.METABOLISM_AUTO_COLLECTIONS:
			try:
				self.apply_erosion(coll.strip())
			except Exception as e:
				logger.error(f"Erosion failed in {coll}: {e}")

	def _refresh_ttl_timestamps(self, collection: str) -> None:
		"""Absence Guard: forward all non-immune last_recalled_at to now.

		Called automatically when idle gap > ABSENCE_THRESHOLD.
		Prevents mass-deletion of the Bunker after long periods of inactivity
		(e.g. the system was powered off or the user was on vacation).
		"""
		now = time.time()
		offset = None
		refreshed = 0

		scroll_filter = models.Filter(
			must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))]
		)

		match_count = 0
		while True:
			try:
				response = self.client.scroll(
					collection_name=collection,
					scroll_filter=scroll_filter,
					limit=200,
					offset=offset,
					with_payload=False,
					with_vectors=False
				)
			except Exception as e:
				logger.error(f"TTL refresh scroll failed: {_mask_pii_exception(e)}")
				break

			point_ids = [hit.id for hit in response[0]]
			if point_ids:
				try:
					self.client.set_payload(
						collection_name=collection,
						payload={"last_recalled_at": now},
						points=point_ids
					)
					refreshed += len(point_ids)
				except Exception as e:
					logger.error(f"TTL refresh payload set failed: {_mask_pii_exception(e)}")

			offset = response[1]
			if offset is None:
				break

			# Safety break for unconfigured mocks in tests
			match_count += 1
			if match_count > 500:
				logger.warning(f"Safety break triggered in TTL refresh for {collection}")
				break

		logger.info(f"Absence Guard: refreshed TTL for {refreshed} engrams in '{collection}'.")



	def _reinforce_points(self, collection: str, point_ids: List[str], increments: Dict[str, float]) -> List[PointUpdate]:
		"""Retrieves and updates reinforcement scores with thread-safety."""
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

		updated_points: List[PointUpdate] = []

		with self._reinforce_lock:
			try:
				points = self.client.retrieve(
					collection_name=collection,
					ids=valid_ids,
					with_payload=True,
					with_vectors=False
				)
			except Exception as e:
				logger.error(f"Reinforcement retrieval failed: {_mask_pii_exception(e)}")
				return []

			for p in points:
				score = p.payload.get("reinforcement_score", 1.0)
				inc = increments.get(str(p.id), increments.get(p.id, 0.0))

				new_score = min(score + inc, cfg.IMMUNITY_THRESHOLD)
				p.payload["reinforcement_score"] = round(new_score, 2)
				p.payload["last_recalled_at"] = time.time()

				if p.payload["reinforcement_score"] >= cfg.IMMUNITY_THRESHOLD:
					p.payload["immune"] = True

				try:
					self.client.set_payload(
						collection_name=collection,
						payload=p.payload,
						points=[p.id]
					)
				except Exception as e:
					logger.error(f"Reinforcement payload set failed: {_mask_pii_exception(e)}")
					continue

				updated_points.append(PointUpdate(id=p.id, payload=p.payload))

		return updated_points

	def search_and_reinforce(self, collection: str, query: str, limit: int = 3, deep_recall: bool = False) -> List[Any]:
		"""Semantic search followed by B760 synaptic reinforcement."""
		vector = self._get_vector(query)

		search_filter = None
		if not deep_recall:
			search_filter = models.Filter(
				must=[models.FieldCondition(key="reinforcement_score", range=models.Range(gte=0.2))]
			)

		try:
			results = self.client.query_points(
				collection_name=collection,
				query=vector,
				query_filter=search_filter,
				limit=limit,
				with_payload=True,
				with_vectors=False
			).points
		except Exception as e:
			logger.error(f"Query failed: {_mask_pii_exception(e)}")
			return []

		increment_map: Dict[str, float] = {}

		for hit in response.points:
			increment_map[hit.id] = cfg.REINFORCEMENT_INCREMENT

		propagation_increment = cfg.REINFORCEMENT_INCREMENT * cfg.PROPAGATION_FACTOR
		for hit in response.points:
			assocs = hit.payload.get("associations", [])
			for assoc_id in assocs:
				increment_map[assoc_id] = increment_map.get(assoc_id, 0.0) + propagation_increment

		if not increment_map:
			return response.points

		points_to_update = self._reinforce_points(collection, list(increment_map.keys()), increment_map)

		if points_to_update:
			update_map = {p.id: p.payload for p in points_to_update}
			for hit in response.points:
				if hit.id in update_map:
					hit.payload.update(update_map[hit.id])

		return response.points

	def _calculate_decay(self, current_score: float, rate: float) -> float:
		"""Computes decay based on the configured strategy."""
		if cfg.DECAY_STRATEGY == "exponential":
			new_score = current_score * (1.0 - rate)
			if round(new_score, 2) >= round(current_score, 2) and current_score > 0:
				new_score = current_score - 0.01
		else:
			new_score = current_score - rate

		return round(max(new_score, 0.0), 2)

	def apply_erosion(self, collection: str, rate: float = None) -> None:
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
			must=[
				models.FieldCondition(
					key="last_recalled_at",
					range=models.Range(lt=ttl_threshold)
				)
			],
			must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))]
		)

		iterations = 0
		while True:
			try:
				response = self.client.scroll(
					collection_name=collection,
					scroll_filter=scroll_filter,
					limit=100,
					offset=offset,
					with_payload=True,
					with_vectors=False
				)
			except Exception as e:
				logger.error(f"Erosion scroll failed: {_mask_pii_exception(e)}")
				break

			points_to_delete: List[Any] = []

			update_operations = []

			for hit in response[0]:
				if hit.payload.get("immune"):
					continue
				current_score = hit.payload.get("reinforcement_score", 1.0)
				color = hit.payload.get("color", "gray")
				multiplier = cfg.EMOTIONAL_DECAY_MULTIPLIERS.get(color, 1.0)

				effective_rate = rate * multiplier
				new_score = self._calculate_decay(current_score, effective_rate)

				if new_score <= 0:
					points_to_delete.append(hit.id)
					deleted_count += 1
				else:
					hit.payload["reinforcement_score"] = new_score
					hit.payload["last_recalled_at"] = time.time()  # Reset TTL after erosion
					update_operations.append(
						models.SetPayloadOperation(
							set_payload=models.SetPayload(
								payload={"reinforcement_score": new_score, "last_recalled_at": time.time()},
								points=[hit.id]
							)
						)
					)

			if update_operations:
				try:
					self.client.batch_update_points(
						collection_name=collection,
						update_operations=update_operations
					)
					eroded_count += len(update_operations)
				except Exception as e:
					logger.error(f"Erosion batch update failed: {_mask_pii_exception(e)}")

			if points_to_delete:
				try:
					self.client.delete(
						collection_name=collection,
						points_selector=models.PointIdsList(points=points_to_delete)
					)
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
		seen_content: Dict[str, str] = {} # content -> id
		duplicates: List[str] = []
		migrated_count = 0

		logger.info(f"Starting sanitation for {collection}...")
		iterations = 0
		while True:
			try:
				response = self.client.scroll(
					collection_name=collection,
					limit=100,
					offset=offset,
					with_payload=True,
					with_vectors=False
				)
			except Exception as e:
				logger.error(f"Sanitation scroll failed: {_mask_pii_exception(e)}")
				break

			update_operations = []

			for hit in response[0]:
				content = hit.payload.get("content", "")

				# 1. Deduplication Check
				if content in seen_content:
					duplicates.append(hit.id)
					continue
				seen_content[content] = hit.id

				# 2. Schema Migration Check
				needs_migration = False
				update_payload = {}

				if "color" not in hit.payload:
					update_payload["color"] = cfg.DEFAULT_COLOR
					needs_migration = True
				if "emotion" not in hit.payload:
					update_payload["emotion"] = cfg.DEFAULT_EMOTION
					needs_migration = True
				if "intensity" not in hit.payload:
					update_payload["intensity"] = 1.0
					needs_migration = True

				if needs_migration:
					if not dry_run:
						update_operations.append(
							models.SetPayloadOperation(
								set_payload=models.SetPayload(
									payload=update_payload,
									points=[hit.id]
								)
							)
						)
					else:
						migrated_count += 1

			if update_operations and not dry_run:
				try:
					self.client.batch_update_points(
						collection_name=collection,
						update_operations=update_operations
					)
					migrated_count += len(update_operations)
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
				self.client.delete(
					collection_name=collection,
					points_selector=models.PointIdsList(points=duplicates)
				)
			except Exception as e:
				logger.error(f"Duplicate deletion failed: {e}")

		return {
			"collection": collection,
			"duplicates_found": len(duplicates),
			"migrated_records": migrated_count,
			"dry_run": dry_run
		}

	def get_stats(self, collection: str) -> Dict[str, Any]:
		"""Returns collection diagnostics."""
		try:
			info = self.client.get_collection(collection_name=collection)
			return {
				"status": getattr(info, "status", "unknown"),
				"points_count": getattr(info, "points_count", 0),
				"segments_count": getattr(info, "segments_count", 0)
			}
		except Exception as e:
			logger.error(f"Stats failed: {e}")
			return {"status": "error", "points_count": 0, "segments_count": 0}
