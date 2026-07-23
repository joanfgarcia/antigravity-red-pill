import asyncio
import logging
import time

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.memory import MemoryManager
from red_pill.swarm.factory import MinionFactory


def report_pain(message: str):
	"""Log a system pain signal to Qdrant (Cortex)."""
	try:
		mgr = MemoryManager()
		mgr.add_memory(
			collection="signal_memories",
			text=f"[QueueWorker] {message}",
			importance=0.8,
			emotion="pain",
			color="orange",
			metadata={"source": "queue_worker", "type": "task_failure"},
		)
		logger.info(f"Pain signal recorded: {message}")
	except Exception as e:
		logger.error(f"Failed to record pain signal: {e}")


logger = logging.getLogger("bunker_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _report_job(job_id: str, task: dict, status: str, content: str) -> None:
	"""Deposita el reporte de fin/error de un job en el MinionInbox (patrón SAS)."""
	try:
		from red_pill.core.inbox import MinionInbox

		title = task.get("payload", {}).get("title") or task.get("source", "job")
		MinionInbox().drop_report(
			event_id=job_id[:8],
			source="JobRunner",
			status=status,
			content=f"Job '{title}' ({task.get('source')}) → {status}: {content}",
			originator=f"queue_worker.process_driver_jobs({job_id})",
		)
	except Exception as e:
		logger.error(f"Failed to report job {job_id} to MinionInbox: {e}")


def process_driver_jobs(cog_queue: CognitiveQueueManager, max_jobs: int = 5) -> int:
	"""Procesa jobs del carril mecánico vía ResumableJobDriver (Centralized Job Manager).

	Reglas de integridad (plan F1): R1 deferral sin attempts, R2 skip-set por
	invocación, R3 releer estado tras cada step (la pausa del operador gana),
	R4 checkpoint persistido tras cada step, R5 recuperación de huérfanos
	acotada a los sources del propio runner.
	"""
	from red_pill.jobs.drivers import registered_sources

	sources = registered_sources()
	if not sources:
		return 0

	# Run-lock (R6): protege las dos vías de entrada (timer systemd y CLI manual).
	# Si otro runner está activo, ceder sin error — el job seguirá ahí.
	lock_file = None
	try:
		import fcntl

		from red_pill.core.paths import get_state_dir

		lock_file = open(get_state_dir() / "job_runner.lock", "w")
		fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
	except BlockingIOError:
		logger.info("Job runner already active; yielding (R6).")
		if lock_file:
			lock_file.close()
		return 0
	except Exception:
		lock_file = None  # FS sin flock: seguimos — el timer systemd ya serializa su propia unit

	try:
		return _process_driver_jobs_locked(cog_queue, sources, max_jobs)
	finally:
		if lock_file:
			lock_file.close()


def _process_driver_jobs_locked(cog_queue: CognitiveQueueManager, sources: list, max_jobs: int) -> int:
	from red_pill.jobs.drivers import JobDeferred, get_driver

	# R5: huérfanos PROCESSING de un crash previo → PENDING (solo carril mecánico)
	cog_queue.requeue_stale(sources)

	completed_jobs = 0
	# R2: todo job ya tratado en esta pasada queda excluido del pop — un diferido
	# re-saldría en bucle estéril y un fallido quemaría el disyuntor en un solo
	# run (el retry le corresponde al siguiente disparo del timer).
	handled_ids: list = []
	for _ in range(max_jobs):
		task = cog_queue.pop_next_task(allowed_sources=sources, exclude_ids=handled_ids)
		if not task:
			break

		job_id = task["id"]
		handled_ids.append(job_id)
		driver = get_driver(task["source"])
		checkpoint = task.get("checkpoint_data") or {}
		logger.info(f"Processing job {job_id} (source: {task['source']}, attempt {task['attempts']})")

		try:
			while True:
				# R1: preflight de entorno antes de CADA step (VRAM/IDE/SIP)
				driver.preflight(task["payload"])
				if driver.min_vram_mb > 0:
					from red_pill.core.vram_probe import VramProbe
					from red_pill.metabolism.phases.consolidation import _check_llm_available

					if not _check_llm_available():
						free_mb = VramProbe.get_free_mb()
						if free_mb < driver.min_vram_mb:
							raise JobDeferred(f"VRAM insuficiente ({free_mb}MB libres < {driver.min_vram_mb}MB)")

				outcome = driver.step(task["payload"], checkpoint)
				checkpoint = outcome.new_checkpoint
				# R4: el checkpoint se persiste inmediatamente tras el step
				cog_queue.save_checkpoint(job_id, checkpoint, outcome.progress)

				if outcome.completed:
					cog_queue.mark_completed(job_id)
					_report_job(job_id, task, "success", outcome.summary or "completed")
					completed_jobs += 1
					break

				# R3: releer estado — una pausa del operador a mitad de step gana
				current = cog_queue.get_task(job_id)
				if current and current.get("status") == "PAUSED":
					logger.info(f"Job {job_id} paused by operator; checkpoint saved, yielding.")
					break

		except JobDeferred as deferral:
			cog_queue.defer_task(job_id)  # R1: PENDING sin attempts++
			logger.info(f"Job {job_id} deferred (no failure): {deferral.reason}")
		except Exception as e:
			cog_queue.mark_failed(job_id, str(e))
			_report_job(job_id, task, "failed", str(e))
			logger.error(f"Job {job_id} step failed: {e}")

	return completed_jobs


def process_cognitive_tasks(cog_queue: CognitiveQueueManager, oneshot: bool = False):
	"""Process up to 5 DAG tasks from the cognitive queue using the Swarm MinionFactory."""
	allowed_sources = list(MinionFactory.MAPPING.keys()) + list(MinionFactory.COMMAND_ALIASES.keys())
	for _ in range(5):
		task = cog_queue.pop_next_task(allowed_sources=allowed_sources)
		if not task:
			break

		logger.info(f"Processing cognitive task {task['id']} from source: {task['source']}")
		try:
			minion = MinionFactory.create(task["source"])
			if not minion:
				raise ValueError(f"MinionFactory failed to create '{task['source']}'")

			payload = task.get("payload", {})

			# Soporte tanto para Minions asíncronos (como Echo) como síncronos
			if asyncio.iscoroutinefunction(minion.execute):
				_ = asyncio.run(minion.execute(**payload))
			else:
				_ = minion.execute(**payload)

			cog_queue.mark_completed(task["id"])
			logger.info(f"Cognitive task {task['id']} completed successfully.")

		except Exception as e:
			cog_queue.mark_failed(task["id"], str(e))
			logger.error(f"Cognitive task {task['id']} failed: {e}")
			report_pain(f"Cognitive Task {task['id']} ({task['source']}) failed: {e}")


def run_queue_worker(poll_interval: int = 5, oneshot: bool = False):
	"""
	Background daemon that consumes the SQLite queues
	and slowly offloads them without blocking the main IDE Agent.
	"""
	logger.info("Starting Bünker Asynchronous Queue Worker (Zero-Daemon)...")
	queue = MemoryQueueManager()

	try:
		cog_queue = CognitiveQueueManager()
	except Exception as e:
		logger.error(f"Queue Worker failed to init CognitiveQueueManager: {e}")
		cog_queue = None

	try:
		memory = MemoryManager()
	except Exception as e:
		logger.error(f"Queue Worker failed to init MemoryManager (Qdrant down?): {e}")
		return

	while True:
		try:
			# 1. Process Cognitive DAG Tasks
			if cog_queue:
				process_cognitive_tasks(cog_queue, oneshot)

			# 1b. Process mechanical driver jobs (Centralized Job Manager)
			if cog_queue:
				process_driver_jobs(cog_queue)

			# 2. Process Memory Queue (Fast Buffer -> Qdrant)
			items = queue.dequeue_pending(limit=10)
			for item in items:
				logger.info(f"Processing queued memory {item['id']} (Prompt: {item['prompt'][:20]}...).")
				queue.update_status(item["id"], "processing")
				try:
					uid = memory.record_interaction_pair(
						prompt=item["prompt"],
						response=item["response"],
						role=item["role"],
						category=item.get("category", "mixed"),
						model=item.get("model"),
					)
					queue.update_status(item["id"], "completed")
					logger.info(f"Memory {item['id']} successfully ingested. (ID: {uid})")
				except Exception as ingest_error:
					logger.error(f"Memory {item['id']} ingestion failed: {ingest_error}")
					queue.update_status(item["id"], "error")

			if not items:
				if oneshot:
					logger.info("No pending items. Oneshot complete.")
					break
				time.sleep(poll_interval)
			elif oneshot:
				# Check if there are more items after the first batch
				if queue.get_pending_count() == 0:
					logger.info("All pending items processed. Oneshot complete.")
					break

		except KeyboardInterrupt:
			logger.info("Terminating Queue Worker.")
			break
		except Exception as e:
			logger.error(f"Queue worker loop error: {e}")
			report_pain(str(e))
			if oneshot:
				break
			time.sleep(poll_interval)


if __name__ == "__main__":
	import argparse

	parser = argparse.ArgumentParser(description="Bünker Asynchronous Queue Worker")
	parser.add_argument("--oneshot", action="store_true", help="Process pending items and exit")
	args = parser.parse_args()

	run_queue_worker(oneshot=args.oneshot)
