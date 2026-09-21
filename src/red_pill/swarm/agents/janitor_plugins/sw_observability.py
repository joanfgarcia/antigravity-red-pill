"""JanitorPlugin: señales de salud del single-writer (D26).

Emite señales de cobertura/frescura para no repetir el fallo "verde con 0
digerido". Solo actúa si alguna pieza del single-writer está activa.
"""

import json
import logging
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class SwObservabilityPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "sw_observability"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		import red_pill.config as cfg

		active = any(
			bool(getattr(cfg, k, False))
			for k in ("SW_HUBS_ENABLED", "SW_SITUATION_ENABLED", "SW_EROSION_DEMOTE_ENABLED", "SW_INGEST_RETIRED", "SW_THREAD_ENABLED")
		)
		if not active:
			return {"skipped": "sw_disabled"}

		from red_pill.memory import MemoryManager
		from red_pill.metabolism.sw_observability import compute_sw_health

		mem = kwargs.get("memory_manager") or MemoryManager()
		health = compute_sw_health(mem)
		janitor.log(f"[Janitor] sw_observability: {health}")

		try:
			if getattr(cfg, "SW_HUBS_ENABLED", False):
				mem.inject_signal(
					name="sw_hub_coverage",
					intensity=2.0,
					signal_type="status",
					source="Janitor",
					message=json.dumps(health.get("collections", {}), ensure_ascii=False),
				)
			age = health.get("solera_age_h")
			if age is not None and age > 168:
				mem.inject_signal(
					name="sw_solera_stale",
					intensity=5.0,
					signal_type="pain",
					source="Janitor",
					message=f"Solera sin actualizar {age}h (¿drenaje/LLM parados?).",
				)
		except Exception as e:
			logger.debug(f"[SW-OBS] señal no inyectada: {e}")
		return health
