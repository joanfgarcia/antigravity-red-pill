"""REVIEW / CANCELLED: reservar un FRUSTRATED de la purga y cerrarlo tras revisar.

El dolor de la cola (2026-11-03): un job FRUSTRATED caduca a los 14 días y el
janitor lo borra sin que nadie lo haya mirado. REVIEW es el aparcamiento
explícito del Operador — el runner no lo ejecuta, `job_health` deja de contarlo
y la purga automática no lo toca. De ahí solo se sale a propósito: `job resume`
(PENDING, se reprocesa) o `job discard` (CANCELLED, se cierra).
"""

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


def _frustrated(queue, source="script_job", title="fallido", age="-1 hour"):
	"""Job en FRUSTRATED con antigüedad controlada (para la ventana de purga)."""
	task_id = queue.enqueue_task(source=source, payload={"title": title})
	with queue._get_connection() as conn:
		conn.execute(
			"UPDATE cognitive_tasks SET status = 'FRUSTRATED', updated_at = datetime('now', ?) WHERE id = ?",
			(age, task_id),
		)
	return task_id


def test_review_reserva_un_frustrated_y_es_idempotente(queue):
	task_id = _frustrated(queue)

	assert queue.mark_review(task_id) is True
	assert queue.get_task(task_id)["status"] == "REVIEW"
	# Reservar dos veces no es un error de estado silencioso: la segunda no aplica.
	assert queue.mark_review(task_id) is False
	assert queue.get_task(task_id)["status"] == "REVIEW"


def test_review_solo_desde_frustrated(queue):
	task_id = queue.enqueue_task(source="script_job", payload={"title": "vivo"})
	assert queue.mark_review(task_id) is False
	assert queue.get_task(task_id)["status"] == "PENDING"


def test_review_undo_devuelve_al_pool_de_purga(queue):
	task_id = _frustrated(queue)
	queue.mark_review(task_id)

	assert queue.mark_review(task_id, undo=True) is True
	assert queue.get_task(task_id)["status"] == "FRUSTRATED"


def test_la_purga_automatica_no_toca_review(queue):
	"""Lo que el Operador reserva no caduca: aunque la fila tenga 90 días."""
	viejo = _frustrated(queue, title="reservado", age="-90 days")
	queue.mark_review(viejo)
	# mark_review refresca updated_at (acto explícito), así que lo envejecemos otra vez.
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET updated_at = datetime('now', '-90 days') WHERE id = ?", (viejo,))
	basura = _frustrated(queue, title="sin revisar", age="-30 days")

	result = queue.purge_hygiene(completed_days=7, frustrated_days=14, stale_processing_hours=24)

	assert result["frustrated_purged"] == 1
	assert queue.get_task(viejo)["status"] == "REVIEW"
	assert queue.get_task(basura) is None


def test_el_barrido_terminal_tampoco_toca_review(queue):
	task_id = _frustrated(queue)
	queue.mark_review(task_id)

	removed = queue.purge_terminal()

	assert removed == 0
	assert queue.get_task(task_id)["status"] == "REVIEW"


def test_resume_desde_review_vuelve_a_pending_sin_intentos(queue):
	task_id = _frustrated(queue)
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET attempts = 3 WHERE id = ?", (task_id,))
	queue.mark_review(task_id)

	assert queue.resume_task(task_id) is True
	task = queue.get_task(task_id)
	assert task["status"] == "PENDING"
	assert task["attempts"] == 0


def test_discard_cierra_en_cancelled_y_cascada(queue):
	padre = queue.enqueue_task(source="script_job", payload={"title": "padre"})
	hijo = queue.enqueue_task(source="script_job", payload={"title": "hijo"}, parent_task_id=padre)
	assert queue.get_task(hijo)["status"] == "BLOCKED"
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET status = 'FRUSTRATED' WHERE id = ?", (padre,))
	queue.mark_review(padre)

	assert queue.mark_cancelled(padre) is True
	assert queue.get_task(padre)["status"] == "CANCELLED"
	# Un hijo de un job descartado no es un fallo que revisar: se cierra igual.
	assert queue.get_task(hijo)["status"] == "CANCELLED"


def test_discard_solo_desde_review_o_frustrated(queue):
	vivo = queue.enqueue_task(source="script_job", payload={"title": "vivo"})
	assert queue.mark_cancelled(vivo) is False
	assert queue.get_task(vivo)["status"] == "PENDING"


def test_review_no_cuenta_como_dolor_ni_la_purga_por_id_lo_respeta(queue):
	task_id = _frustrated(queue)
	queue.mark_review(task_id)

	health = queue.job_health(sources=["script_job"])
	assert health["frustrated"] == 0
	assert queue.frustrated_jobs(sources=["script_job"]) == []

	# Retirar la reserva a mano sí se puede: es un acto explícito del Operador.
	assert queue.purge_task(task_id) is True
	assert queue.get_task(task_id) is None


def test_list_tasks_muestra_review_por_defecto(queue):
	task_id = _frustrated(queue)
	queue.mark_review(task_id)

	visibles = {t["id"]: t["status"] for t in queue.list_tasks()}
	assert visibles.get(task_id) == "REVIEW"


def test_cancelled_tampoco_entra_en_la_purga_automatica(queue):
	"""CANCELLED es el registro de una decisión: no cae por la ventana temporal."""
	task_id = _frustrated(queue)
	queue.mark_review(task_id)
	queue.mark_cancelled(task_id)
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET updated_at = datetime('now', '-90 days') WHERE id = ?", (task_id,))

	queue.purge_hygiene(completed_days=7, frustrated_days=14, stale_processing_hours=24)

	assert queue.get_task(task_id)["status"] == "CANCELLED"
