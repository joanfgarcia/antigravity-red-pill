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

# Tope de jobs que se citan en el mensaje: el dolor debe ser legible, no un volcado.
FRUSTRATED_ATTRIBUTION_LIMIT = 10


def frustrated_message(jobs: list) -> str:
	"""Mensaje del dolor `jobs_frustrated`: quién lo sostiene, no solo cuántos.

	El payload del job no siempre trae título; se cae a source/id para que el
	operador pueda reconocerlo sin abrir la cola.
	"""
	if not jobs:
		return "[PAIN] jobs_frustrated — sin atribución disponible (jobs ilegibles)."
	parts = []
	for job in jobs:
		label = job.get("title") or job.get("source") or "?"
		age = job.get("age_hours")
		age_txt = f", {age}h" if isinstance(age, int) and age >= 0 else ""
		parts.append(f"{str(job.get('id', '?'))[:8]} '{label}'{age_txt}")
	return f"[PAIN] jobs_frustrated — {len(jobs)} job(s) FRUSTRATED: " + " · ".join(parts)


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

		sources = registered_sources()
		health = self._queue.job_health(sources, stuck_after_seconds=STUCK_AFTER_SECONDS)

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
			attribution = self._queue.frustrated_jobs(sources, limit=FRUSTRATED_ATTRIBUTION_LIMIT)
			logger.warning(f"[JOB-MONITOR] {health['frustrated']} job(s) FRUSTRATED (disyuntor activado).")
			self._mm.inject_signal(
				"jobs_frustrated",
				intensity=5.0,
				signal_type="pain",
				source="JobMonitor",
				message=frustrated_message(attribution),
			)
		else:
			self._mm.evaporate_signals("jobs_frustrated")
