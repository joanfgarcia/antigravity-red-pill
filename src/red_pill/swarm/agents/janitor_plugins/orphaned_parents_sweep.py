import logging
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class OrphanedParentsSweepPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "orphaned_parents_sweep"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running orphaned_parents_sweep plugin...")
		purged_work = 0
		purged_social = 0

		try:
			from red_pill.memory import MemoryManager

			memory_manager = MemoryManager()
			purged_work = self._cleanup_orphaned_parents(janitor, memory_manager, "work_memories")
			purged_social = self._cleanup_orphaned_parents(janitor, memory_manager, "social_memories")
			janitor.log(f"[Janitor] Purged {purged_work} orphaned parents from work_memories and {purged_social} from social_memories.")
		except Exception as e:
			logger.error(f"[Janitor] Failed to execute orphaned parent sweep: {e}")
			janitor.log(f"[Janitor] Error running orphaned parent sweep: {e}")

		return {"orphaned_parents_purged": purged_work + purged_social}

	def _cleanup_orphaned_parents(self, janitor: Any, memory_manager: Any, collection_name: str) -> int:
		from qdrant_client.http import models

		deleted_count = 0
		if not memory_manager.client.collection_exists(collection_name):
			return 0
		try:
			offset = None
			parent_points = []
			while True:
				records, next_offset = memory_manager.client.scroll(
					collection_name=collection_name,
					scroll_filter=models.Filter(must=[models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent"))]),
					limit=100,
					offset=offset,
					with_payload=True,
					with_vectors=False,
				)
				parent_points.extend(records)
				if next_offset is None:
					break
				offset = next_offset

			for parent in parent_points:
				payload = parent.payload or {}
				associations = payload.get("associations", [])
				child_ids = []
				for assoc in associations:
					if isinstance(assoc, dict):
						child_ids.append(assoc.get("id"))
					else:
						child_ids.append(str(assoc))

				if not child_ids:
					try:
						memory_manager.client.delete(collection_name=collection_name, points_selector=models.PointIdsList(points=[parent.id]))
						deleted_count += 1
					except Exception:
						pass
					continue

				child_exists = False
				for col in ["work_memories", "social_memories"]:
					try:
						found = memory_manager.client.retrieve(collection_name=col, ids=child_ids, with_payload=False, with_vectors=False)
						if found:
							child_exists = True
							break
					except Exception:
						pass

				if not child_exists:
					try:
						memory_manager.client.delete(collection_name=collection_name, points_selector=models.PointIdsList(points=[parent.id]))
						deleted_count += 1
					except Exception:
						pass

		except Exception as e:
			logger.error(f"[Janitor] Failed orphaned parents sweep in {collection_name}: {e}")
			janitor.log(f"[Janitor] Error sweeping collection {collection_name}: {e}")
		return deleted_count
