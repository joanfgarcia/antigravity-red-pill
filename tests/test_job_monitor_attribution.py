"""Atribución del dolor `jobs_frustrated`: el job_monitor dice QUIÉN sostiene el dolor.

Antes, `inject_signal("jobs_frustrated")` no llevaba mensaje y el dashboard sólo
mostraba un recuento; con el escalado de dolor, ese número satura a 10 en pocos
ticks y deja de distinguir un falso positivo de una avería real.
"""

import json

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.daemon.plugins.job_monitor import frustrated_message


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


def _enqueue(queue, source="script_job", title="job de prueba", status="FRUSTRATED", hours_old=3):
	task_id = queue.enqueue_task(source=source, payload={"title": title} if title else {})
	with queue._get_connection() as conn:
		conn.execute(
			"UPDATE cognitive_tasks SET status = ?, updated_at = datetime('now', ?) WHERE id = ?",
			(status, f"-{int(hours_old)} hours", task_id),
		)
	return task_id


def test_frustrated_jobs_attributes_id_title_and_age(queue):
	"""El dolor cita id, título (del payload) y edad en horas de cada job."""
	task_id = _enqueue(queue, title="CI main tras merge #131", hours_old=11)

	jobs = queue.frustrated_jobs(["script_job"])

	assert len(jobs) == 1
	assert jobs[0]["id"] == task_id
	assert jobs[0]["title"] == "CI main tras merge #131"
	assert jobs[0]["source"] == "script_job"
	assert jobs[0]["age_hours"] == pytest.approx(11, abs=1)


def test_frustrated_jobs_ignores_other_statuses_and_sources(queue):
	"""Solo FRUSTRATED del carril mecánico: un PAUSED o un source ajeno no es dolor."""
	_enqueue(queue, title="vivo", status="PAUSED")
	_enqueue(queue, source="drive_evaluator", title="carril cognitivo")

	assert queue.frustrated_jobs(["script_job"]) == []


def test_frustrated_jobs_honours_limit_and_orders_newest_first(queue):
	"""El tope evita volcar la cola entera; el más reciente va primero."""
	old = _enqueue(queue, title="viejo", hours_old=48)
	new = _enqueue(queue, title="nuevo", hours_old=1)

	jobs = queue.frustrated_jobs(["script_job"], limit=1)

	assert [job["id"] for job in jobs] == [new]
	assert old not in [job["id"] for job in jobs]


def test_frustrated_jobs_without_sources_is_empty(queue):
	"""Sin sources registrados no hay carril que vigilar (ni query)."""
	assert queue.frustrated_jobs([]) == []


def test_frustrated_message_names_every_job(queue):
	"""El mensaje que viaja al dashboard identifica los jobs, no sólo cuántos son."""
	jobs = [
		{"id": "ff2516a3-0000-0000-0000-000000000000", "title": "CI main", "age_hours": 11},
		{"id": "8c522050-0000-0000-0000-000000000000", "title": "", "source": "script_job", "age_hours": 2},
	]

	message = frustrated_message(jobs)

	assert "2 job(s) FRUSTRATED" in message
	assert "ff2516a3 'CI main', 11h" in message
	assert "8c522050 'script_job', 2h" in message  # sin título cae al source


def test_frustrated_message_without_attribution_is_explicit():
	"""Si la cola no devuelve filas, el mensaje lo dice en vez de mentir con un 0."""
	assert "sin atribución" in frustrated_message([])
	assert json.dumps(frustrated_message([]))  # sigue siendo serializable para Qdrant


def test_operator_discard_does_not_sustain_pain(queue):
	"""Un job descartado A PROPÓSITO no es dolor: el Operador ya cerró el asunto.

	Medido el 2026-11-10: la misión NB-001 se descartó a mano, la cola la selló
	FRUSTRATED con `error_log: cancelled by operator` y el JobMonitor mantuvo un
	WARNING de intensidad 5 (escalado a 7) durante 14 días de dead-letter. Desde
	2026-11-12 el descarte nace CANCELLED — el recuento ya no depende de leer el
	texto del error, y el rastro no caduca con la dead-letter.
	"""
	task_id = queue.enqueue_task(source="script_job", payload={"title": "misión descartada"})
	queue.pop_next_task(allowed_sources=["script_job"])
	assert queue.kill_task(task_id, discard=True) is True
	assert queue.get_task(task_id)["status"] == "CANCELLED"  # la cola conserva el rastro

	assert queue.job_health(["script_job"])["frustrated"] == 0
	assert queue.frustrated_jobs(["script_job"]) == []


def test_legacy_operator_discard_row_does_not_sustain_pain(queue):
	"""Filas LEGACY (`FRUSTRATED` + `cancelled by operator`): siguen sin doler.

	Una cola viva al desplegar este cambio arrastra descartes sellados con el
	estado viejo hasta que caduque su dead-letter; el filtro por `error_log`
	existe solo para ellas y no puede caer sin resucitar el dolor de 2026-11-10.
	"""
	task_id = _enqueue(queue, title="misión descartada (legacy)")
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET error_log = 'cancelled by operator' WHERE id = ?", (task_id,))

	assert queue.job_health(["script_job"])["frustrated"] == 0
	assert queue.frustrated_jobs(["script_job"]) == []


def test_cancelled_job_survives_hygiene_and_cannot_be_resurrected(queue):
	"""CANCELLED es un acto del Operador: la purga automática no lo retira y
	`resume` no lo resucita (se re-encola, no se des-cancela)."""
	task_id = queue.enqueue_task(source="script_job", payload={"title": "cerrado a mano"})
	assert queue.kill_task(task_id, discard=True) is True

	queue.purge_hygiene(completed_days=0, frustrated_days=0, stale_processing_hours=24)
	assert queue.get_task(task_id)["status"] == "CANCELLED"
	assert queue.resume_task(task_id) is False
	assert queue.get_task(task_id)["status"] == "CANCELLED"


def test_real_frustration_still_sustains_pain(queue):
	"""El disyuntor de verdad sigue doliendo: el filtro no silencia los fallos."""
	task_id = _enqueue(queue, title="falló 3 veces")
	with queue._get_connection() as conn:
		conn.execute(
			"UPDATE cognitive_tasks SET error_log = 'JobStepTimeout: step excedió la cota' WHERE id = ?",
			(task_id,),
		)

	assert queue.job_health(["script_job"])["frustrated"] == 1
	assert [job["id"] for job in queue.frustrated_jobs(["script_job"])] == [task_id]


def test_discarded_parent_cascade_does_not_sustain_pain(queue):
	"""La cascada de un padre descartado (`parent cancelled`) tampoco es dolor."""
	parent = queue.enqueue_task(source="script_job", payload={"title": "padre"})
	child = queue.enqueue_task(source="script_job", payload={"title": "hijo"}, parent_task_id=parent)
	assert queue.get_task(child)["status"] == "BLOCKED"

	assert queue.kill_task(parent, discard=True) is True
	assert queue.get_task(child)["status"] == "CANCELLED"

	assert queue.job_health(["script_job"])["frustrated"] == 0
	assert queue.frustrated_jobs(["script_job"]) == []
