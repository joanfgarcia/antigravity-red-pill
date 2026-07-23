"""Centralized Job Manager F1: ResumableJobDriver + runner integrity rules R1-R5."""

import sqlite3
from typing import Any, Dict

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_worker import process_driver_jobs
from red_pill.jobs.drivers import _REGISTRY, JobDeferred, ResumableJobDriver, StepOutcome, register_driver


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
	"""Keep job reports away from the real MinionInbox during tests."""
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda *a, **kw: None)


class CountingDriver(ResumableJobDriver):
	"""Completes after payload['total'] steps, counting via checkpoint."""

	source = "test_counting"

	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		done = checkpoint_data.get("done", 0) + 1
		total = payload.get("total", 3)
		return StepOutcome(
			completed=done >= total,
			new_checkpoint={"done": done},
			summary=f"{done}/{total}",
			progress={"current_step": done, "total_steps": total, "percent": round(100 * done / total)},
		)


def test_schema_migration_preserves_existing_rows(tmp_path):
	"""A pre-F1 database opens clean, gains the new columns and keeps its rows."""
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
		conn.execute("INSERT INTO cognitive_tasks (id, source, payload) VALUES ('old-1', 'drive_evaluator', '{}')")

	queue = CognitiveQueueManager(db_path=str(db_path))
	task = queue.pop_next_task()
	assert task is not None and task["id"] == "old-1"
	assert task["checkpoint_data"] == {}


def test_driver_steps_to_completion_with_checkpoints(queue, clean_registry):
	register_driver(CountingDriver)
	job_id = queue.enqueue_task(source="test_counting", payload={"total": 3})

	assert process_driver_jobs(queue) == 1

	task = queue.get_task(job_id)
	assert task["status"] == "COMPLETED"
	assert task["checkpoint_data"] == {"done": 3}
	assert task["progress"]["percent"] == 100


def test_resume_continues_from_exact_checkpoint(queue, clean_registry):
	"""A job interrupted mid-way resumes from its persisted checkpoint, not from zero."""
	register_driver(CountingDriver)
	job_id = queue.enqueue_task(source="test_counting", payload={"total": 5})
	# Simulate a previous partial run: checkpoint at 3/5, back in PENDING.
	queue.save_checkpoint(job_id, {"done": 3}, {"current_step": 3, "total_steps": 5, "percent": 60})

	steps_run = []
	original_step = CountingDriver.step

	def spy_step(self, payload, checkpoint_data):
		steps_run.append(checkpoint_data.get("done", 0))
		return original_step(self, payload, checkpoint_data)

	CountingDriver.step = spy_step
	try:
		process_driver_jobs(queue)
	finally:
		CountingDriver.step = original_step

	assert steps_run == [3, 4]  # resumed at 3 -> steps 4 and 5, never 1-3 again
	assert queue.get_task(job_id)["status"] == "COMPLETED"


def test_pause_wins_mid_job_and_resume_reactivates(queue, clean_registry):
	"""R3: a pause during a running job stops the loop at the next step boundary."""

	class PausingDriver(ResumableJobDriver):
		source = "test_pausing"
		_queue = None
		_job_id = None

		def step(self, payload, checkpoint_data):
			done = checkpoint_data.get("done", 0) + 1
			if done == 2:
				PausingDriver._queue.pause_task(PausingDriver._job_id)  # operator pauses mid-run
			return StepOutcome(completed=done >= 10, new_checkpoint={"done": done})

	register_driver(PausingDriver)
	job_id = queue.enqueue_task(source="test_pausing", payload={})
	PausingDriver._queue, PausingDriver._job_id = queue, job_id

	assert process_driver_jobs(queue) == 0

	task = queue.get_task(job_id)
	assert task["status"] == "PAUSED"
	assert task["checkpoint_data"] == {"done": 2}  # step's progress was preserved

	assert queue.resume_task(job_id)
	assert queue.get_task(job_id)["status"] == "PENDING"


def test_deferral_keeps_attempts_untouched(queue, clean_registry):
	"""R1: environment deferral returns the job to PENDING without feeding the breaker."""

	class DeferringDriver(ResumableJobDriver):
		source = "test_deferring"

		def preflight(self, payload):
			raise JobDeferred("VRAM busy")

		def step(self, payload, checkpoint_data):
			raise AssertionError("step must not run when preflight defers")

	register_driver(DeferringDriver)
	job_id = queue.enqueue_task(source="test_deferring", payload={})

	process_driver_jobs(queue)

	task = queue.get_task(job_id)
	assert task["status"] == "PENDING"
	assert task["attempts"] == 0


def test_deferred_job_excluded_within_same_run(queue, clean_registry):
	"""R2: after a deferral the same top-priority job is not re-popped in this run,
	so lower-priority jobs of other mechanical sources still get processed."""
	preflight_calls = []

	class GpuDriver(ResumableJobDriver):
		source = "test_gpu"

		def preflight(self, payload):
			preflight_calls.append(1)
			raise JobDeferred("VRAM busy")

		def step(self, payload, checkpoint_data):
			raise AssertionError("unreachable")

	register_driver(GpuDriver)
	register_driver(CountingDriver)
	queue.enqueue_task(source="test_gpu", payload={}, priority=10)
	cpu_job = queue.enqueue_task(source="test_counting", payload={"total": 1}, priority=1)

	assert process_driver_jobs(queue) == 1  # the CPU job completed despite the GPU block
	assert len(preflight_calls) == 1  # the deferred job was popped exactly once
	assert queue.get_task(cpu_job)["status"] == "COMPLETED"


def test_real_failure_feeds_the_breaker(queue, clean_registry):
	"""A genuine step failure goes through mark_failed: attempts+1, FRUSTRATED at 3."""

	class FailingDriver(ResumableJobDriver):
		source = "test_failing"

		def step(self, payload, checkpoint_data):
			raise RuntimeError("boom")

	register_driver(FailingDriver)
	job_id = queue.enqueue_task(source="test_failing", payload={})

	for expected_attempts in (1, 2, 3):
		process_driver_jobs(queue)
		task = queue.get_task(job_id)
		assert task["attempts"] == expected_attempts

	assert task["status"] == "FRUSTRATED"


def test_stale_recovery_scoped_to_runner_sources(queue, clean_registry):
	"""R5: orphaned PROCESSING jobs of runner sources recover; cognitive ones stay."""
	register_driver(CountingDriver)
	job_id = queue.enqueue_task(source="test_counting", payload={"total": 1})
	cognitive_id = queue.enqueue_task(source="drive_evaluator", payload={"action": "autonomous_research"})

	# Both get popped (simulating a crash right after) and backdated.
	queue.pop_next_task(allowed_sources=["test_counting"])
	queue.pop_next_task(allowed_sources=["drive_evaluator"])
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET updated_at = datetime('now', '-1 hour')")

	recovered = queue.requeue_stale(["test_counting"], older_than_seconds=900)

	assert recovered == 1
	assert queue.get_task(job_id)["status"] == "PENDING"
	assert queue.get_task(job_id)["attempts"] == 1
	assert queue.get_task(cognitive_id)["status"] == "PROCESSING"  # cognitive lane untouched
