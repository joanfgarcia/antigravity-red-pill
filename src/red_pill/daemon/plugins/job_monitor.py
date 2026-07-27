"""Job Monitor Plugin — vigila el carril mecánico del Centralized Job Manager.

MONITOR-ONLY (doctrina del SovereignDaemon): lee la salud de la cola y
dispara/evapora señales. Jamás ejecuta ni recupera jobs — la recuperación
de huérfanos (R5) pertenece al runner shot-and-forget.
"""

import logging

from red_pill.daemon.plugin import DaemonPlugin

logger = logging.getLogger("red_pill.daemon.plugins.job_monitor")

# Un job PROCESSING sin latido (updated_at) en este margen se considera atascado.
# El runner refresca updated_at en cada checkpoint, así que steps largos legítimos
# siguen latiendo; 30 min sin latido = crash o cuelgue real.
STUCK_AFTER_SECONDS = 1800


class JobMonitorPlugin(DaemonPlugin):
	@property
	def name(self) -> str:
		return "job_monitor"

	@property
	def interval_s(self) -> float:
		return 300.0

	@property
	def timeout_s(self) -> float:
		return 5.0

	async def on_start(self) -> None:
		from red_pill.cognitive.queue_manager import CognitiveQueueManager
		from red_pill.memory import MemoryManager

		self._mm = MemoryManager()
		self._queue = CognitiveQueueManager()

	async def tick(self) -> None:
		from red_pill.jobs.drivers import registered_sources

		health = self._queue.job_health(registered_sources(), stuck_after_seconds=STUCK_AFTER_SECONDS)

		if health["stuck"]:
			logger.warning(f"[JOB-MONITOR] {health['stuck']} job(s) PROCESSING sin latido > {STUCK_AFTER_SECONDS}s.")
			self._mm.inject_signal(
				"jobs_stuck",
				intensity=6.0,
				signal_type="pain",
				source="JobMonitor",
			)
		else:
			self._mm.evaporate_signals("jobs_stuck")

		if health["frustrated"]:
			logger.warning(f"[JOB-MONITOR] {health['frustrated']} job(s) FRUSTRATED (disyuntor activado).")
			self._mm.inject_signal(
				"jobs_frustrated",
				intensity=5.0,
				signal_type="pain",
				source="JobMonitor",
			)
		else:
			self._mm.evaporate_signals("jobs_frustrated")
