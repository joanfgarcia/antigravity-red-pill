"""Queue hygiene — autolimpieza nocturna de la cola central (bunker_queue.db).

Borra COMPLETED/FRUSTRATED antiguos y marca como FRUSTRATED (dead-letter, con
señal de dolor `queue_stuck_tasks`) los PROCESSING colgados sin latido. Solo
alcanza a los carriles sin recuperación propia (samantha, cognitivo): el carril
mecánico de drivers se auto-recupera vía requeue_stale a los 15 minutos.
"""

import logging
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class QueueHygienePlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "queue_hygiene"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running queue_hygiene plugin...")
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})

		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		hygiene = CognitiveQueueManager().purge_hygiene(
			completed_days=plugin_cfg.get("completed_days_to_keep", 7),
			frustrated_days=plugin_cfg.get("frustrated_days_to_keep", 14),
			stale_processing_hours=plugin_cfg.get("stale_processing_hours", 24),
		)
		janitor.log(
			f"[Janitor] Queue hygiene: {hygiene['completed_purged']} completed y {hygiene['frustrated_purged']} "
			f"frustrated purgados, {hygiene['stuck_marked']} colgados marcados FRUSTRATED."
		)

		if hygiene["stuck_marked"]:
			try:
				from red_pill.memory import MemoryManager

				MemoryManager().inject_signal(
					name="queue_stuck_tasks",
					intensity=6.0,
					signal_type="pain",
					source="Janitor",
					originator=f"queue_hygiene ({hygiene['stuck_marked']} tareas colgadas en PROCESSING)",
				)
			except Exception as sig_err:
				logger.warning(f"[Janitor] Failed to inject queue_stuck_tasks signal: {sig_err}")

		return hygiene
