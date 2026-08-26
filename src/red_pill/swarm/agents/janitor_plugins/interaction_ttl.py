"""TTL backstop de `interaction_memories` (RFC-002 §4.4 / S3, Fase 3).

El Sleep ya auto-drena el buffer al consolidar; esto solo barre lo que el
drenaje deja atrás (failed_ids que hoy quedan para siempre, noches con la
VRAM llena). El almacenamiento raw duradero es Memento — Qdrant conserva solo
la ventana caliente.

Guardarraíl: el TTL debe superar la ventana del pre-heating (config 48h y el
hardcode 48h de 11_pre_heating.py:234) — si no, el plugin se niega a purgar.
Los puntos llevan el epoch en `timestamp` (memory.py:513); se filtra también
`created_at` por si generaciones antiguas lo usaron.
"""

import logging
import time
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)

PRE_HEATING_HARDCODED_FLOOR_HOURS = 48  # 11_pre_heating.py tier-2


class InteractionTTLPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "interaction_ttl"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		from qdrant_client.http import models

		import red_pill.config as cfg
		from red_pill.memory import MemoryManager

		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		ttl_hours = int(plugin_cfg.get("ttl_hours", getattr(cfg, "INTERACTION_MEMORIES_TTL_HOURS", 72)))
		floor = max(int(getattr(cfg, "PRE_HEATING_LOOKBACK_HOURS", 48)), PRE_HEATING_HARDCODED_FLOOR_HOURS)
		if ttl_hours <= floor:
			janitor.log(f"[Janitor] interaction_ttl SKIPPED: TTL {ttl_hours}h no supera la ventana del pre-heating ({floor}h).")
			return {"purged": 0, "skipped": "ttl_below_preheating_window"}

		cutoff = time.time() - ttl_hours * 3600
		mem = kwargs.get("memory_manager") or MemoryManager()
		collection = "interaction_memories"
		if not mem.client.collection_exists(collection):
			return {"purged": 0}

		stale_filter = models.Filter(
			should=[
				models.FieldCondition(key="timestamp", range=models.Range(lt=cutoff)),
				models.FieldCondition(key="created_at", range=models.Range(lt=cutoff)),
			]
		)
		stale = mem.client.count(collection, count_filter=stale_filter, exact=True).count
		if stale:
			mem.client.delete(collection, points_selector=models.FilterSelector(filter=stale_filter), wait=True)
		janitor.log(f"[Janitor] interaction_ttl: {stale} punto(s) más viejos de {ttl_hours}h purgados del buffer.")
		return {"purged": stale, "ttl_hours": ttl_hours}
