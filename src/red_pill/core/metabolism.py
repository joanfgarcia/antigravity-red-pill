import json
import logging
import threading
import time
from typing import Any, List, Optional

from qdrant_client.http import models

import red_pill.config as cfg
from red_pill.affect import get_memory_engine

logger = logging.getLogger(__name__)


def _mask_pii_exception(e: Exception) -> str:
	msg = str(e)
	return msg if len(msg) < 150 else msg[:150] + "... [TRUNCATED]"


class MetabolismKernel:
	"""Handles biological decay processes: Erosion, Purging, and TTL Refreshing."""

	def __init__(self, storage_engine: Any, config: Any = None):
		self.cfg = config if config else cfg
		self.storage = storage_engine
		self._metabolism_thread: Optional[threading.Thread] = None

	def trigger(self) -> None:
		"""Persistent background process to check and execute erosion."""
		if self._metabolism_thread is not None and self._metabolism_thread.is_alive():
			return

		try:
			self._metabolism_thread = threading.Thread(target=self._run_cycle, daemon=True)
			self._metabolism_thread.start()
		except Exception as e:
			logger.error(f"Metabolism thread launch failed: {e}")

	def _read_state(self, f: Any) -> tuple[float, bool]:
		f.seek(0)
		content = f.read().strip()
		if not content:
			return 0.0, False
		try:
			state = json.loads(content)
			if isinstance(state, dict):
				return float(state.get("last_run", 0.0)), bool(state.get("skip_next_erosion", False))
			return float(state), False
		except (ValueError, TypeError, json.JSONDecodeError):
			return 0.0, False

	def _write_state(self, f: Any, last_run: float, skip_next_erosion: bool = False) -> None:
		f.seek(0)
		f.truncate()
		json.dump({"last_run": last_run, "skip_next_erosion": skip_next_erosion}, f)
		f.flush()

	def _run_cycle(self) -> None:
		state_file = self.cfg.METABOLISM_STATE_FILE
		now = time.time()

		try:
			from filelock import FileLock, Timeout

			lock = FileLock(state_file + ".lock", timeout=0)
			with lock:
				with open(state_file, "a+") as f:
					last_run, skip_next_erosion = self._read_state(f)
					gap = now - last_run if last_run > 0 else float("inf")

					if last_run > 0 and gap < self.cfg.METABOLISM_COOLDOWN:
						return

					abs_gap = now - last_run if last_run > 0 else 0
					if abs_gap > self.cfg.ABSENCE_THRESHOLD:
						logger.warning(
							f"Absence detected ({round(abs_gap / 86400, 1)} days). Running TTL refresh to protect the Bunker. Erosion skipped for this cycle and the next."
						)
						for coll in self.cfg.METABOLISM_AUTO_COLLECTIONS:
							try:
								self.refresh_ttl_timestamps(coll.strip())
							except Exception as e:
								logger.error(f"TTL refresh failed during absence recovery for {coll}: {e}")

						self._write_state(f, now, skip_next_erosion=True)
						logger.info("Absence Guard triggered: Bunker refreshed and erosion short-circuited for this cycle.")
						return

					if skip_next_erosion:
						logger.info(
							"CQ-001: skip_next_erosion flag active — skipping erosion this cycle to protect freshly-refreshed post-vacation engrams."
						)
						self._write_state(f, now, skip_next_erosion=False)
						return

					self._write_state(f, now, skip_next_erosion=False)

		except Timeout:
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
		timestamp_limite = time.time() - self.cfg.MAX_SINK_TIME

		try:
			self.storage.delete(
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

	def refresh_ttl_timestamps(self, collection: str) -> None:
		now = time.time()
		offset = None
		refreshed = 0
		scroll_filter = models.Filter(must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))])

		match_count = 0
		while True:
			try:
				response = self.storage.scroll(
					collection_name=collection, scroll_filter=scroll_filter, limit=200, offset=offset, with_payload=False, with_vectors=False
				)
			except Exception as e:
				logger.error(f"TTL refresh scroll failed: {_mask_pii_exception(e)}")
				break

			point_ids = [hit.id for hit in response[0]]
			if point_ids:
				try:
					self.storage.set_payload(collection_name=collection, payload={"last_recalled_at": now}, points=point_ids)
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

	def apply_erosion(self, collection: str, rate: Optional[float] = None) -> None:
		if rate is None:
			rate = self.cfg.EROSION_RATE
		if rate <= 0:
			return
		if rate > 0.5:
			logger.warning(f"High erosion rate detected ({rate}). Significant memory loss imminent.")
		eroded_count = 0
		deleted_count = 0
		ttl_threshold = time.time() - self.cfg.METABOLISM_COOLDOWN
		scroll_filter = models.Filter(
			must=[models.FieldCondition(key="last_recalled_at", range=models.Range(lt=ttl_threshold))],
			must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))],
		)

		from red_pill.schemas import EngramPayload

		def _parse_payload(payload: Any) -> Any:
			try:
				validated = EngramPayload.model_validate(payload)
				return validated.model_dump()
			except Exception:
				return payload

		for batch in self.storage.scroll_generator(collection, scroll_filter=scroll_filter, limit=100, max_iterations=1000):
			points_to_delete: List[Any] = []
			update_operations = []
			for hit in batch:
				if hit.payload is None or hit.payload.get("immune"):
					continue

				hit.payload = _parse_payload(hit.payload)

				engine_type = self.cfg.MEMORY_ENGINES.get(collection.strip(), "fsrs_real")
				engine = get_memory_engine(engine_type)

				decay_updates = engine.calculate_lazy_decay(hit.payload, current_time=time.time())

				if decay_updates.get("_delete"):
					points_to_delete.append(str(hit.id))
					deleted_count += 1
				elif decay_updates:
					eroded_count += 1
					decay_updates["last_recalled_at"] = time.time()
					update_operations.append(
						models.SetPayloadOperation(
							set_payload=models.SetPayload(
								payload=decay_updates,
								points=[hit.id],
							)
						)
					)
			if update_operations:
				try:
					self.storage.batch_update_points(collection_name=collection, update_operations=update_operations)
				except Exception as e:
					logger.error(f"Erosion batch update failed: {_mask_pii_exception(e)}")
			if points_to_delete:
				try:
					self.storage.delete(collection_name=collection, points_selector=models.PointIdsList(points=points_to_delete))
				except Exception as e:
					logger.error(f"Erosion delete failed: {_mask_pii_exception(e)}")

		logger.info(f"Erosion complete in {collection}. Updated: {eroded_count}, Deleted: {deleted_count}")
