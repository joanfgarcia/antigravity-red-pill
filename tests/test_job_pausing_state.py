from unittest.mock import MagicMock

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_worker import _process_driver_jobs_locked


@pytest.fixture
def queue(tmp_path):
	db_path = str(tmp_path / "test_queue.db")
	return CognitiveQueueManager(db_path=db_path)


def test_pause_task_transitions(queue):
	# 1. PENDING -> PAUSED
	task_id_1 = queue.enqueue_task(source="script_job", payload={"title": "Pending Job"})
	ok_1 = queue.pause_task(task_id_1)
	assert ok_1 is True
	task_1 = queue.get_task(task_id_1)
	assert task_1["status"] == "PAUSED"

	# 2. PROCESSING -> PAUSING
	task_id_2 = queue.enqueue_task(source="script_job", payload={"title": "Processing Job"})
	# Pop to make it PROCESSING
	popped = queue.pop_next_task(allowed_sources=["script_job"])
	assert popped["id"] == task_id_2
	assert queue.get_task(task_id_2)["status"] == "PROCESSING"

	ok_2 = queue.pause_task(task_id_2)
	assert ok_2 is True
	task_2 = queue.get_task(task_id_2)
	assert task_2["status"] == "PAUSING"

	# 3. Invalid transition from PAUSING -> False
	assert queue.pause_task(task_id_2) is False


def test_resume_task_cancels_pausing(queue):
	task_id = queue.enqueue_task(source="script_job", payload={"title": "Test Job"})
	queue.pop_next_task(allowed_sources=["script_job"])  # -> PROCESSING

	# Request pause -> PAUSING
	assert queue.pause_task(task_id) is True
	assert queue.get_task(task_id)["status"] == "PAUSING"

	# Resume while PAUSING -> PROCESSING (cancels pause request)
	ok_res = queue.resume_task(task_id)
	assert ok_res is True
	assert queue.get_task(task_id)["status"] == "PROCESSING"


def test_resume_task_from_paused_and_frustrated(queue):
	task_id = queue.enqueue_task(source="script_job", payload={"title": "Test Job"})
	queue.pause_task(task_id)  # PENDING -> PAUSED

	assert queue.resume_task(task_id) is True
	assert queue.get_task(task_id)["status"] == "PENDING"


def test_runner_pausing_to_paused_at_step_boundary(queue, monkeypatch):
	task_id = queue.enqueue_task(source="script_job", payload={"title": "Script Test Job"})

	mock_driver = MagicMock()
	mock_outcome_1 = MagicMock()
	mock_outcome_1.completed = False
	mock_outcome_1.new_checkpoint = {"epoch": 1}
	mock_outcome_1.progress = {"current": 1, "total": 10}

	mock_driver.step.return_value = mock_outcome_1
	mock_driver.min_vram_mb = 0

	monkeypatch.setattr("red_pill.jobs.drivers.registered_sources", lambda: ["script_job"])
	monkeypatch.setattr("red_pill.jobs.drivers.get_driver", lambda source: mock_driver)

	# Before worker starts step 2, pause the task -> PAUSING
	def on_step_boundary():
		queue.pause_task(task_id)

	processed = _process_driver_jobs_locked(cog_queue=queue, sources=["script_job"], max_jobs=1, on_step_boundary=on_step_boundary)

	# The driver executed step 1, hit on_step_boundary which set status=PAUSING,
	# and at the step boundary check line, worker transitioned PAUSING -> PAUSED and broke loop.
	assert processed == 0
	task = queue.get_task(task_id)
	assert task["status"] == "PAUSED"
	assert task["checkpoint_data"] == {"epoch": 1}
	assert mock_driver.step.call_count == 1
