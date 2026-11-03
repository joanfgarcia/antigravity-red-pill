"""`job_health` no confunde "paso largo" con "atasco" (falso positivo 2026-11-03).

El ciclo nocturno pasó horas en un `annotate` de 1.500 mensajes; la fila del job
solo se escribe en frontera de step, así que `job_health` la vio quieta >30 min y
encendió `jobs_stuck` mientras el hijo trabajaba. El latido fino vive en el
fichero de control (`job_progress_age_s`, RFC-JOBDAG-002 F4); si ese fichero está
fresco, el job respira aunque `updated_at` esté congelado.
"""

import os

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core import progress


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "q.db"))


def _processing_quieto(queue, source="script_job"):
	"""Job en PROCESSING con la fila congelada hace 2 h (como un step largo)."""
	task_id = queue.enqueue_task(source=source, payload={"title": "paso largo"})
	pop = queue.pop_next_task(allowed_sources=[source])
	assert pop and pop["id"] == task_id
	with queue._get_connection() as conn:
		conn.execute(
			"UPDATE cognitive_tasks SET updated_at = datetime('now', '-2 hours') WHERE id = ?",
			(task_id,),
		)
	return task_id


def _latido(tmp_path, monkeypatch, age_s: float):
	path = tmp_path / "job.progress.json"
	path.write_text('{"label": "extract", "current": 1, "total": 10}', encoding="utf-8")
	now = __import__("time").time()
	os.utime(path, (now - age_s, now - age_s))
	monkeypatch.setattr(progress, "job_progress_path", lambda _job_id: path)
	return path


def test_fichero_fresco_no_es_atasco(queue, tmp_path, monkeypatch):
	_processing_quieto(queue)
	_latido(tmp_path, monkeypatch, age_s=30)

	health = queue.job_health(["script_job"], stuck_after_seconds=1800)

	assert health == {"stuck": 0, "frustrated": 0}


def test_sin_fichero_sigue_siendo_atasco(queue, tmp_path, monkeypatch):
	_processing_quieto(queue)
	monkeypatch.setattr(progress, "job_progress_path", lambda _job_id: tmp_path / "no-existe.json")

	assert queue.job_health(["script_job"], stuck_after_seconds=1800)["stuck"] == 1


def test_fichero_viejo_sigue_siendo_atasco(queue, tmp_path, monkeypatch):
	_processing_quieto(queue)
	_latido(tmp_path, monkeypatch, age_s=4000)  # más que el umbral

	assert queue.job_health(["script_job"], stuck_after_seconds=1800)["stuck"] == 1


def test_un_job_cancelado_no_cuenta_como_atasco(queue, tmp_path, monkeypatch):
	task_id = _processing_quieto(queue)
	monkeypatch.setattr(progress, "job_progress_path", lambda _job_id: tmp_path / "no-existe.json")
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET cancel_requested_at = 1.0 WHERE id = ?", (task_id,))

	assert queue.job_health(["script_job"], stuck_after_seconds=1800)["stuck"] == 0
