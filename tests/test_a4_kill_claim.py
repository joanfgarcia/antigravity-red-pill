"""A4 — la cancelación gana siempre a la reclamación (kill↔claim monotónico).

Contrato que se verifica aquí: una vez que el Operador mata un job, **ninguna
transición del runner** puede devolverlo a la vida (`PENDING`) ni sellarlo como
`COMPLETED`. Solo dos puertas explícitas (`resume`, `skip`) limpian la marca,
porque son órdenes del Operador sobre un job detenido.

Antes de A4 la resurrección era real: kill sobre un job `PROCESSING` → `PAUSED`,
el step en vuelo lanzaba excepción → `mark_failed` → `attempts++` y `PENDING`
→ `pop_next_task` lo reclamaba otra vez.
"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_worker import process_driver_jobs
from red_pill.jobs.drivers import _REGISTRY, ResumableJobDriver, StepOutcome, register_driver


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


@pytest.fixture
def clean_registry():
	saved = dict(_REGISTRY)
	_REGISTRY.clear()
	yield _REGISTRY
	_REGISTRY.clear()
	_REGISTRY.update(saved)


@pytest.fixture(autouse=True)
def silent_reports(monkeypatch):
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda *a, **kw: None)


# ── La marca monotónica existe y se sella en el kill ──────────────────────


def test_kill_seals_monotonic_cancel_mark(queue):
	"""Un kill sobre un job en vuelo deja marca de cancelación con tiempo real."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	assert queue.pop_next_task()["id"] == job_id
	assert queue.is_cancel_requested(job_id) is False

	assert queue.kill_task(job_id) is True
	row = queue.get_task(job_id)
	assert row["status"] == "PAUSED"
	assert row["cancel_requested_at"] is not None
	assert queue.is_cancel_requested(job_id) is True


def test_migration_adds_cancel_column_to_legacy_db(tmp_path):
	"""Una BD pre-A4 gana la columna en blanco y conserva sus filas vivas."""
	db_path = tmp_path / "bunker_queue.db"
	with sqlite3.connect(db_path) as conn:
		conn.execute("""
			CREATE TABLE cognitive_tasks (
				id TEXT PRIMARY KEY, source TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 5,
				payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				attempts INTEGER NOT NULL DEFAULT 0, error_log TEXT
			)
		""")
		conn.execute("INSERT INTO cognitive_tasks (id, source, payload) VALUES ('old-a4', 'samantha', '{}')")

	legacy = CognitiveQueueManager(db_path=str(db_path))
	assert legacy.is_cancel_requested("old-a4") is False
	assert legacy.pop_next_task()["id"] == "old-a4"  # la fila antigua sigue siendo reclamable


# ── El fallo del step en vuelo YA NO resucita el job ─────────────────────


def test_failed_step_after_kill_does_not_resurrect(queue):
	"""El corazón de A4: kill → excepción del step → el job NO vuelve a PENDING."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	assert queue.pop_next_task()["id"] == job_id
	queue.kill_task(job_id)

	queue.mark_failed(job_id, "boom tras el kill")

	row = queue.get_task(job_id)
	assert row["status"] == "PAUSED"  # ni PENDING ni FRUSTRATED
	assert row["attempts"] == 0  # no se quema intento en un job cancelado
	assert row["error_log"] == "boom tras el kill"  # el fallo queda anotado
	assert queue.pop_next_task() is None  # y nadie lo vuelve a reclamar


def test_failed_step_after_discard_keeps_frustrated(queue):
	"""Con `discard`, el fallo del step tampoco reabre el circuito."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	queue.pop_next_task()
	queue.kill_task(job_id, discard=True)

	queue.mark_failed(job_id, "boom tras el discard")

	row = queue.get_task(job_id)
	assert row["status"] == "FRUSTRATED"
	assert row["attempts"] == 0


def test_failure_after_pause_does_not_requeue(queue):
	"""La pausa del Operador tiene el mismo privilegio: un fallo no la deshace."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	queue.pop_next_task()
	assert queue.pause_task(job_id) is True  # PROCESSING → PAUSING

	queue.mark_failed(job_id, "boom durante la pausa")

	assert queue.get_task(job_id)["status"] == "PAUSING"
	assert queue.get_task(job_id)["attempts"] == 0


def test_completion_after_kill_is_refused(queue):
	"""Un step que termina bien tras el kill no puede sellar COMPLETED."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	queue.pop_next_task()
	queue.kill_task(job_id)

	queue.mark_completed(job_id)

	row = queue.get_task(job_id)
	assert row["status"] == "PAUSED"
	assert row["cancel_requested_at"] is not None


def test_defer_cannot_revive_cancelled_job(queue):
	"""El deferral por entorno (R1) tampoco devuelve a PENDING un job cancelado."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	queue.pop_next_task()
	queue.kill_task(job_id)

	assert queue.defer_task(job_id) is False
	assert queue.get_task(job_id)["status"] == "PAUSED"


# ── Las dos puertas explícitas del Operador SÍ limpian la marca ───────────


def test_resume_clears_cancel_mark(queue):
	"""`job_resume` es la puerta legítima: limpia la marca y el job vuelve a la cola."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	queue.pop_next_task()
	queue.kill_task(job_id)

	assert queue.resume_task(job_id) is True
	row = queue.get_task(job_id)
	assert row["status"] == "PENDING"
	assert row["cancel_requested_at"] is None
	assert queue.pop_next_task()["id"] == job_id
	queue.mark_completed(job_id)
	assert queue.get_task(job_id)["status"] == "COMPLETED"  # reanudado, sí puede cerrar


def test_skip_clears_cancel_mark(queue):
	"""`job_skip` sobre un job detenido también es orden explícita: limpia la marca."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	queue.pop_next_task()
	queue.kill_task(job_id)

	assert queue.skip_next_task(job_id) is True
	row = queue.get_task(job_id)
	assert row["status"] == "PENDING"
	assert row["cancel_requested_at"] is None
	assert row["checkpoint_data"]["skip_next"] is True


# ── Defensa en el reclamador y en la recuperación de huérfanos ────────────


def test_pop_never_claims_pending_row_with_cancel_mark(queue):
	"""Si una fila quedó PENDING con marca (estado imposible por diseño), no se reclama."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	with sqlite3.connect(queue.db_path) as conn:
		conn.execute("UPDATE cognitive_tasks SET cancel_requested_at = 1.0 WHERE id = ?", (job_id,))

	assert queue.pop_next_task() is None
	assert queue.get_task(job_id)["status"] == "PENDING"


def test_stale_recovery_ignores_cancelled_jobs(queue):
	"""El barrido de huérfanos no resucita un PROCESSING cancelado."""
	job_id = queue.enqueue_task(source="samantha", payload={})
	queue.pop_next_task()
	queue.kill_task(job_id)
	# Estado imposible (cancelado pero PROCESSING): lo fuerza el test para
	# verificar que la recuperación de huérfanos también respeta la marca.
	with sqlite3.connect(queue.db_path) as conn:
		conn.execute(
			"UPDATE cognitive_tasks SET status = 'PROCESSING', updated_at = datetime('now', '-2 hours') WHERE id = ?",
			(job_id,),
		)

	assert queue.requeue_stale(["samantha"], older_than_seconds=900) == 0
	assert queue.recover_stale_processing("samantha", older_than_seconds=900) == 0
	assert queue.get_task(job_id)["status"] == "PROCESSING"


# ── Carrera real: pop y kill en paralelo ─────────────────────────────────


def test_concurrent_pop_and_kill_never_resurrect(queue):
	"""20 rondas de pop↔kill concurrentes: el estado final nunca es reclamable."""
	for _ in range(20):
		job_id = queue.enqueue_task(source="samantha", payload={})

		def pop() -> Any:
			return queue.pop_next_task()

		def kill() -> Any:
			return queue.kill_task(job_id)

		with ThreadPoolExecutor(max_workers=2) as pool:
			pop_future = pool.submit(pop)
			kill_future = pool.submit(kill)
			pop_future.result()
			kill_future.result()

		row = queue.get_task(job_id)
		assert row["status"] in ("PAUSED", "FRUSTRATED", "PENDING")
		if row["status"] == "PENDING":
			# Solo puede ser PENDING si el kill llegó antes del pop: entonces
			# el kill NO se aplicó (job no reclamado) y la marca está limpia.
			assert queue.is_cancel_requested(job_id) is False
		else:
			assert queue.is_cancel_requested(job_id) is True
			queue.mark_failed(job_id, "boom")
			assert queue.get_task(job_id)["status"] == row["status"]
			assert queue.get_task(job_id)["attempts"] == 0


# ── Runner real: un step que revienta después del kill no reintenta ───────


class SuicideDriver(ResumableJobDriver):
	"""Mata el job desde dentro del step y luego revienta (la carrera canónica)."""

	source = "test_suicide"
	queue_ref: CognitiveQueueManager = None  # type: ignore[assignment]

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		self.queue_ref.kill_task(payload["job_id"])
		raise RuntimeError("step reventado tras el kill")


def test_runner_reports_kill_not_retry_when_step_dies_after_kill(queue, clean_registry, monkeypatch):
	"""El runner debe reportar `killed`, no un reintento que ya no existe."""
	reports = []
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda job_id, task, kind, msg: reports.append(kind))

	SuicideDriver.queue_ref = queue
	register_driver(SuicideDriver)
	job_id = queue.enqueue_task(source="test_suicide", payload={"job_id": ""})
	# El id solo se conoce tras encolar: se reescribe el payload en la fila.
	with sqlite3.connect(queue.db_path) as conn:
		conn.execute("UPDATE cognitive_tasks SET payload = ? WHERE id = ?", (f'{{"job_id": "{job_id}"}}', job_id))

	process_driver_jobs(queue)

	row = queue.get_task(job_id)
	assert row["status"] == "PAUSED"
	assert row["attempts"] == 0
	assert row["cancel_requested_at"] is not None
	assert "killed" in reports
	assert "failed" not in reports
