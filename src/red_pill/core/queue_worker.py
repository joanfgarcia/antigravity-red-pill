import asyncio
import json
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


def _clean_turn(prompt: str, response: str) -> "tuple[str, str]":
	"""Strip terminal/CI noise from a captured turn before it becomes memory.

	Returns empty strings when nothing of substance survives, so a turn that was
	pure tooling chatter is dropped instead of polluting the buffer. This used to
	live only in the interceptor relay, which meant turns captured by the editor
	hooks bypassed it entirely.
	"""
	try:
		from red_pill.utils.telemetry_filter import filter_noise_from_turn

		clean_prompt = filter_noise_from_turn(prompt or "")
		clean_response = filter_noise_from_turn(response or "")
	except Exception as e:
		logger.warning(f"Noise filter unavailable, ingesting raw: {e}")
		return prompt, response

	if len(clean_prompt.strip()) <= 20 and len(clean_response.strip()) <= 20:
		return "", ""
	return clean_prompt, clean_response


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


def _handle_step_timeout(cog_queue: CognitiveQueueManager, job_id: str, task: dict, timeout) -> None:
	"""Muerte por cota de tiempo: rastro forense triple y escalada por intento.

	La huella va a tres sitios porque cada uno responde una pregunta distinta:
	el log del job (¿qué estaba haciendo?), `error_log` (¿qué pasó?, visible en
	`job status`) y la marca del checkpoint (¿estaba bien calibrada la cota?,
	comparando `bound_s` con la media real). Los dos primeros vencimientos son
	el sistema curándose solo — se avisa sin alarma; el tercero exige juicio.
	"""
	from red_pill.jobs.drivers import append_job_log

	forensics = timeout.forensics()
	detail = (
		f"STEP TIMEOUT: abatido a los {forensics['elapsed_s'] / 60:.1f} min "
		f"(cota {forensics['bound_s'] / 60:.1f} min, media {forensics['ema_s'] / 60:.1f} min, intento {forensics['attempt']}/3)"
	)

	append_job_log(job_id, detail)
	cog_queue.mark_dirty_kill(job_id, forensics)
	cog_queue.mark_failed(job_id, detail)

	if forensics["attempt"] >= 3:
		_report_job(job_id, task, "failed", f"{detail} — disyuntor activado, requiere revisión del operador.")
		report_pain(f"Job {job_id[:8]} ({task.get('source')}) agotó el disyuntor por timeouts: {detail}")
	else:
		# Reintento con cota duplicada: un step legítimamente degradado a CPU
		# sobrevive al siguiente intento sin despertar a nadie de madrugada.
		_report_job(job_id, task, "warning", f"{detail} — reintento automático con cota duplicada.")


def _nightly_cycle_active() -> "str | None":
	"""Nombre del ciclo nocturno activo (sueño 03:00 / chronicle 04:00) o None.

	Los ciclos metabólicos tienen prioridad absoluta sobre los driver jobs: la
	comprobación primaria es la unit systemd ACTIVA (cubre toda la duración del
	ciclo — el fichero de estado del sueño solo se refresca al inicio de cada
	fase y una fase larga lo dejaría "rancio"). El fichero queda como respaldo
	para ejecuciones manuales (`red-pill sleep`) fuera de systemd.
	"""
	try:
		import subprocess

		for unit in ("redpill-sleep.service", "redpill-chronicle.service"):
			# Las units nocturnas son Type=oneshot: mientras su ExecStart corre
			# reportan "activating", nunca "active" — con `--quiet` (rc==0 solo
			# para "active") este check fue ciego toda la madrugada del 28 jul y
			# la carrera de VRAM contra el sueño frustró el entrenamiento de Bit.
			state = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True, timeout=3).stdout.strip()
			if state in ("active", "activating", "reloading"):
				return unit
	except Exception:
		pass

	try:
		from red_pill.core.paths import get_state_dir

		sleep_status_file = get_state_dir() / "sleep_phase_status.json"
		if sleep_status_file.exists():
			data = json.loads(sleep_status_file.read_text(encoding="utf-8"))
			if data.get("status") == "running" and (time.time() - data.get("updated_at", 0)) < 300:
				return "sleep_cycle (manual)"
	except Exception:
		pass

	return None


def process_driver_jobs(cog_queue: CognitiveQueueManager, max_jobs: int = 5, on_step_boundary=None) -> int:
	"""Procesa jobs del carril mecánico vía ResumableJobDriver (Centralized Job Manager).

	Reglas de integridad (plan F1): R1 deferral sin attempts, R2 skip-set por
	invocación, R3 releer estado tras cada step (la pausa del operador gana),
	R4 checkpoint persistido tras cada step, R5 recuperación de huérfanos
	acotada a los sources del propio runner.

	`on_step_boundary` se invoca entre step y step de un job en curso: un
	entrenamiento continuo retiene esta función HORAS en una sola invocación,
	y sin ese respiradero el resto del worker (la ingesta de memory_queue) se
	quedaría en ayunas todo ese tiempo. Un fallo del callback nunca puede
	tumbar el job.
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
		return _process_driver_jobs_locked(cog_queue, sources, max_jobs, on_step_boundary)
	finally:
		if lock_file:
			lock_file.close()


def _process_driver_jobs_locked(cog_queue: CognitiveQueueManager, sources: list, max_jobs: int, on_step_boundary=None) -> int:
	from red_pill.jobs.drivers import JobDeferred, JobPauseRequested, JobStepTimeout, compute_step_timeout, get_driver, update_step_ema

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
		progress = task.get("progress") or {}
		logger.info(f"Processing job {job_id} (source: {task['source']}, attempt {task['attempts']})")

		try:
			while True:
				# R1: preflight de entorno antes de CADA step (VRAM/IDE/SIP/ciclos nocturnos)
				# Exención anti-deadlock (RFC_SLEEP_JOB_DRIVER §2.3): si el sueño es un
				# driver job, su propio fichero "running" lo diferiría a sí mismo entre
				# unidades → inanición. El source sleep_job se exime; los ajenos siguen
				# difiriendo mientras el fichero esté fresco (prioridad nocturna deseada).
				nightly = _nightly_cycle_active()
				if nightly and task["source"] != "sleep_job":
					raise JobDeferred(f"Ciclo nocturno con prioridad absoluta en ejecución: {nightly}")

				# La cota de tiempo es política del RUNNER, uniforme para todos los
				# drivers; el driver solo la aplica (scope con RuntimeMaxSec).
				driver.bind(job_id, task["attempts"], compute_step_timeout(task["payload"], progress, task["attempts"]))
				driver.preflight(task["payload"])
				if driver.min_vram_mb > 0:
					from red_pill.core.vram_probe import VramProbe

					free_mb = VramProbe.get_free_mb()
					if free_mb < driver.min_vram_mb:
						raise JobDeferred(f"VRAM insuficiente ({free_mb}MB libres < {driver.min_vram_mb}MB)")

				started = time.time()
				outcome = driver.step(task["payload"], checkpoint)
				checkpoint = outcome.new_checkpoint
				# La media móvil de duración alimenta a la vez el ETA y la cota del
				# siguiente step: se mide aquí para que ningún driver la reimplemente.
				progress = update_step_ema(outcome.progress, time.time() - started)
				# R4: el checkpoint se persiste inmediatamente tras el step
				cog_queue.save_checkpoint(job_id, checkpoint, progress)

				if outcome.completed:
					cog_queue.mark_completed(job_id)
					_report_job(job_id, task, "success", outcome.summary or "completed")
					completed_jobs += 1
					break

				# Respiradero entre steps: el job sigue, pero el resto del worker
				# no puede esperar horas a que termine. Blindado — la ingesta de
				# memorias jamás justifica perder un entrenamiento.
				if on_step_boundary:
					try:
						on_step_boundary()
					except Exception as e:
						logger.warning(f"Step-boundary callback failed (job {job_id} continues): {e}")

				# R3: releer estado — una pausa del operador a mitad de step gana (PAUSING/PAUSED)
				current = cog_queue.get_task(job_id)
				if current and current.get("status") in ("PAUSING", "PAUSED"):
					cog_queue.mark_paused(job_id)
					logger.info(f"Job {job_id} reached step boundary while {current.get('status')}; checkpoint saved, now PAUSED.")
					break

				# Cesión por prioridad en frontera de step: un job de mayor prioridad
				# recién encolado (el sueño de las 03:00 frente a un entrenamiento de
				# días) no puede esperar a que este complete — la prioridad solo
				# ordena pops. Se comprueba DESPUÉS de al menos un step: un job alto
				# no-ejecutable (GPU externa ocupada, se difiere una y otra vez) no
				# debe matar de hambre al resto, así que cada invocación garantiza
				# progreso antes de volver a ceder el turno.
				if cog_queue.has_higher_priority_pending(sources, int(task.get("priority") or 5)):
					raise JobDeferred("cede el paso a un job PENDING de mayor prioridad")

		except JobDeferred as deferral:
			cog_queue.defer_task(job_id)  # R1: PENDING sin attempts++
			logger.info(f"Job {job_id} deferred (no failure): {deferral.reason}")
		except JobPauseRequested as pause:
			# El satélite pidió juicio humano (pause_exit_code): PAUSED con el
			# checkpoint intacto y cero intentos — `job resume` cuando el operador
			# haya revisado. Se reporta como aviso, no como dolor.
			cog_queue.mark_paused(job_id)
			_report_job(job_id, task, "warning", f"Pausado a petición del propio job: {pause.reason}")
			logger.info(f"Job {job_id} paused at its own request: {pause.reason}")
		except JobStepTimeout as timeout:
			_handle_step_timeout(cog_queue, job_id, task, timeout)
			logger.error(f"Job {job_id} step timed out: {timeout}")
		except Exception as e:
			# Extensión de R3: el operador puede haber abatido el step a propósito
			# (`job kill`, que sella PAUSED ANTES de parar el scope). Un rc≠0 de esa
			# causa no es un fallo del job: ni quema intentos ni levanta alarma.
			current = cog_queue.get_task(job_id)
			if current and current.get("status") in ("PAUSED", "FRUSTRATED") and (current.get("checkpoint_data") or {}).get("dirty_kill"):
				logger.info(f"Job {job_id} killed by operator; checkpoint preserved, no attempt burned.")
			else:
				cog_queue.mark_failed(job_id, str(e))
				_report_job(job_id, task, "failed", str(e))
				logger.error(f"Job {job_id} step failed: {e}")
		finally:
			# Teardown en TODAS las salidas, deferral incluido: sin esto, un job que
			# cede ante el ciclo de sueño dejaría el residente descargado toda la noche.
			try:
				driver.teardown(task["payload"])
			except Exception as e:
				logger.warning(f"Job {job_id} teardown failed: {e}")

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


def drain_memory_queue(queue: MemoryQueueManager, memory: MemoryManager, limit: int = 10, max_batches: int = 1) -> int:
	"""Drena memory_queue hacia Qdrant (Fast Buffer -> engramas). Devuelve items tratados.

	`max_batches` permite vaciar backlog acumulado (p.ej. tras un driver job de
	horas) sin convertir el drenaje en un bucle sin cota: se detiene en cuanto
	un lote llega incompleto o al agotar los lotes concedidos.
	"""
	processed = 0
	for _ in range(max_batches):
		items = queue.dequeue_pending(limit=limit)
		for item in items:
			logger.info(f"Processing queued memory {item['id']} (Prompt: {item['prompt'][:20]}...).")
			queue.update_status(item["id"], "processing")
			try:
				# Noise filtering lives HERE, at the single drain point, instead of
				# in each capture surface: the editor hooks are deliberately dumb
				# (and the JS one cannot call Python at all), so cleaning once on
				# the way out keeps every producer honest and identical.
				clean_prompt, clean_response = _clean_turn(item["prompt"], item["response"])
				if not clean_prompt and not clean_response:
					queue.update_status(item["id"], "completed")
					logger.info(f"Memory {item['id']} dropped: nothing but tooling noise after trimming.")
					continue

				uid = memory.record_interaction_pair(
					prompt=clean_prompt,
					response=clean_response,
					role=item["role"],
					category=item.get("category", "mixed"),
					model=item.get("model"),
					originator=item.get("originator"),
				)
				queue.update_status(item["id"], "completed")
				logger.info(f"Memory {item['id']} successfully ingested. (ID: {uid})")
			except Exception as ingest_error:
				logger.error(f"Memory {item['id']} ingestion failed: {ingest_error}")
				queue.update_status(item["id"], "error")

		processed += len(items)
		if len(items) < limit:
			break
	return processed


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
			# 1. Memory Queue PRIMERO: los turnos capturados por los hooks son lo
			# más perecedero del ciclo. Con el orden antiguo, un driver job de
			# horas los dejaba sin ingerir toda su duración (ingesta diferida).
			# max_batches>1 absorbe backlog sin retrasar los otros carriles en
			# régimen normal (un lote incompleto corta en seco).
			drained = drain_memory_queue(queue, memory, limit=10, max_batches=5)

			# 2. Process Cognitive DAG Tasks
			if cog_queue:
				process_cognitive_tasks(cog_queue, oneshot)

			# 3. Mechanical driver jobs (Centralized Job Manager). Puede retener
			# el bucle HORAS (entrenamiento continuo): el respiradero entre steps
			# mantiene viva la ingesta de memorias mientras tanto.
			if cog_queue:
				process_driver_jobs(cog_queue, on_step_boundary=lambda: drain_memory_queue(queue, memory, limit=10))

			if not drained:
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
