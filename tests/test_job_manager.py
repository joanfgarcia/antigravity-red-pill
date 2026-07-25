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


class _FakeResult:
	def __init__(self, status):
		self.status = status


class _FakeOrchestrator:
	"""Two-step flow; deploy results are scripted per minion."""

	workspace_root = "/tmp"

	def __init__(self, flow, outcomes):
		self._flow = flow
		self._outcomes = outcomes
		self.deployed = []

		class _Engine:
			def get_flow(_self, flow_id, cwd=None):
				return flow if flow_id == "test_flow" else None

		self.flow_engine = _Engine()

	async def deploy_swarm(self, task, minions, trace=True, **kwargs):
		self.deployed.append(minions[0])
		return [_FakeResult(self._outcomes[minions[0]])]


def test_flow_job_driver_checkpoints_per_stage(queue, clean_registry):
	"""F3 pilot: flows become pausable/resumable — checkpoint is the stage index."""
	from red_pill.jobs.drivers.flow import FlowJobDriver

	flow = {"steps": [{"minion": "linter"}, {"minion": "auditor", "on_fail": "stop"}]}
	fake = _FakeOrchestrator(flow, {"linter": "success", "auditor": "success"})

	driver = FlowJobDriver()
	driver._orchestrator = fake

	first = driver.step({"flow_id": "test_flow"}, {})
	assert not first.completed
	assert first.new_checkpoint == {"step_index": 1, "results": ["linter: success"]}
	assert first.progress == {"current_step": 1, "total_steps": 2, "percent": 50}

	second = driver.step({"flow_id": "test_flow"}, first.new_checkpoint)
	assert second.completed
	assert fake.deployed == ["linter", "auditor"]


def test_flow_job_driver_on_fail_stop_raises_with_checkpoint_intact(queue, clean_registry):
	"""A failed stage with on_fail: stop is a real job failure (breaker path),
	and the checkpoint still points at the failed stage for a resumed retry."""
	from red_pill.jobs.drivers.flow import FlowJobDriver

	flow = {"steps": [{"minion": "linter"}, {"minion": "auditor", "on_fail": "stop"}]}
	fake = _FakeOrchestrator(flow, {"linter": "success", "auditor": "failed"})

	driver = FlowJobDriver()
	driver._orchestrator = fake

	checkpoint = driver.step({"flow_id": "test_flow"}, {}).new_checkpoint
	with pytest.raises(RuntimeError, match="stopped at step 1"):
		driver.step({"flow_id": "test_flow"}, checkpoint)
	# The checkpoint the runner persisted before the failure still targets stage 1.
	assert checkpoint["step_index"] == 1


class _FakeBridge:
	def __init__(self, healthy=True, response="done", error=None):
		self._healthy = healthy
		self._response = response
		self._error = error
		self.prompt_calls = []

	def health_check(self):
		return self._healthy

	def prompt(self, text, **kwargs):
		self.prompt_calls.append((text, kwargs))

		class _R:
			response = self._response
			error = self._error
			conversation_id = "conv-1"
			ok = self._error is None

		return _R()


def test_agentic_job_driver_routes_policy_to_bridge(queue, clean_registry, monkeypatch):
	"""D1: payload policy (backend/model/effort/cwd) reaches the bridge untouched."""
	from red_pill.jobs.drivers.agentic import AgenticJobDriver

	fake = _FakeBridge()
	captured = {}

	def fake_create(backend=None, **kw):
		captured["backend"] = backend
		return fake

	monkeypatch.setattr("red_pill.swarm.bridges.factory.create_bridge", fake_create)

	driver = AgenticJobDriver()
	payload = {"prompt": "audit the repo", "backend": "claude", "model": "opus", "effort": "high", "cwd": "/tmp/ws"}
	driver.preflight(payload)
	outcome = driver.step(payload, {})

	assert captured["backend"] == "claude"
	text, kwargs = fake.prompt_calls[-1]
	assert text == "audit the repo"
	assert kwargs == {"timeout": 600, "model": "opus", "effort": "high", "cwd": "/tmp/ws"}
	assert outcome.completed
	assert outcome.new_checkpoint["conversation_id"] == "conv-1"


def test_bit_training_driver_preflight_and_step(tmp_path, monkeypatch):
	from red_pill.jobs.drivers.bit_training import BitTrainingDriver
	driver = BitTrainingDriver()

	# Preflight check without systemd error
	monkeypatch.setattr("red_pill.core.vram_probe.VramProbe.get_free_mb", lambda: 8000)
	driver.preflight({"min_vram_mb": 1000})

	# Test step with mock checkpoint file
	fake_fs = tmp_path / "frankenswarm"
	chk_dir = fake_fs / "sto_rage".replace("_", "") / "checkpoints"
	chk_dir.mkdir(parents=True, exist_ok=True)
	chk_file = chk_dir / "sovereign_school_state.json"
	chk_file.write_text('{"last_completed_epoch": 5}')

	def mock_run(cmd, **kw):
		class DummyProc:
			returncode = 0
			stdout = "Step done"
			stderr = ""
		return DummyProc()

	monkeypatch.setattr("subprocess.run", mock_run)

	outcome = driver.step({
		"cwd": str(fake_fs),
		"checkpoint_file": str(chk_file),
		"target_epochs": 10,
	}, {})

	assert outcome.completed is False
	assert outcome.progress["current"] == 5
	assert outcome.progress["total"] == 10


def test_agentic_job_driver_defers_when_backend_down(queue, clean_registry, monkeypatch):
	"""R1: IDE closed / SIP down is a deferral, never a breaker-feeding failure."""
	from red_pill.jobs.drivers.agentic import AgenticJobDriver

	monkeypatch.setattr("red_pill.swarm.bridges.factory.create_bridge", lambda backend=None, **kw: _FakeBridge(healthy=False))

	driver = AgenticJobDriver()
	with pytest.raises(JobDeferred):
		driver.preflight({"prompt": "x", "backend": "agy"})


def test_agentic_job_driver_cascade_order(queue, clean_registry, monkeypatch):
	"""cascade payload builds BridgeTargets in declared order."""
	from red_pill.jobs.drivers.agentic import AgenticJobDriver

	captured = {}

	def fake_cascade(targets, name="cascade"):
		captured["targets"] = [(t.backend, t.model, t.effort) for t in targets]
		return _FakeBridge()

	monkeypatch.setattr("red_pill.swarm.bridges.factory.create_cascade_bridge", fake_cascade)

	driver = AgenticJobDriver()
	payload = {
		"prompt": "research",
		"cascade": [
			{"backend": "claude", "model": "opus", "effort": "high"},
			{"backend": "local", "model": "samantha"},
		],
	}
	outcome = driver.step(payload, {})

	assert captured["targets"][0] == ("claude", "opus", "high")
	assert captured["targets"][1][0] == "local"
	assert outcome.completed


def test_job_health_reports_stuck_and_frustrated_scoped(queue, clean_registry):
	"""job_monitor input: stuck/frustrated counts are scoped to runner sources."""
	register_driver(CountingDriver)
	stuck_id = queue.enqueue_task(source="test_counting", payload={})
	queue.enqueue_task(source="drive_evaluator", payload={})

	queue.pop_next_task(allowed_sources=["test_counting"])  # -> PROCESSING
	queue.pop_next_task(allowed_sources=["drive_evaluator"])  # cognitive lane, also PROCESSING
	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET updated_at = datetime('now', '-1 hour')")
		conn.execute("UPDATE cognitive_tasks SET status = 'FRUSTRATED' WHERE id != ?", (stuck_id,))

	health = queue.job_health(["test_counting"], stuck_after_seconds=1800)

	assert health == {"stuck": 1, "frustrated": 0}  # the cognitive lane never counts


def test_runner_flock_second_runner_yields(queue, clean_registry, tmp_path, monkeypatch):
	"""R6: while one runner holds the lock, a concurrent run exits 0 without popping."""
	import fcntl

	from red_pill.core import paths

	state_dir = tmp_path / "state"
	state_dir.mkdir()
	monkeypatch.setattr(paths, "get_state_dir", lambda: state_dir)

	register_driver(CountingDriver)
	job_id = queue.enqueue_task(source="test_counting", payload={"total": 1})

	holder = open(state_dir / "job_runner.lock", "w")
	fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
	try:
		assert process_driver_jobs(queue) == 0
		assert queue.get_task(job_id)["status"] == "PENDING"  # untouched
	finally:
		holder.close()

	assert process_driver_jobs(queue) == 1  # lock released -> normal run


def test_vram_deferral_via_probe(queue, clean_registry, monkeypatch):
	"""A GPU driver defers (checkpoint intact, no attempts) when VramProbe reports no headroom."""
	from red_pill.core.vram_probe import VramProbe

	class GpuStepDriver(ResumableJobDriver):
		source = "test_gpu_step"
		min_vram_mb = 4000

		def step(self, payload, checkpoint_data):
			return StepOutcome(completed=True, new_checkpoint={"ran": True})

	register_driver(GpuStepDriver)
	job_id = queue.enqueue_task(source="test_gpu_step", payload={})
	queue.save_checkpoint(job_id, {"done": 2}, None)

	monkeypatch.setattr(VramProbe, "get_free_mb", staticmethod(lambda: 512))
	assert process_driver_jobs(queue) == 0
	task = queue.get_task(job_id)
	assert task["status"] == "PENDING"
	assert task["attempts"] == 0
	assert task["checkpoint_data"] == {"done": 2}

	monkeypatch.setattr(VramProbe, "get_free_mb", staticmethod(lambda: 8000))
	assert process_driver_jobs(queue) == 1


def test_sleep_cycle_defers_driver_jobs(queue, clean_registry, tmp_path, monkeypatch):
	"""While the metabolic sleep cycle is running (fresh heartbeat), driver jobs
	defer cleanly (R1: PENDING, no attempts). A stale 'running' file (>300s,
	e.g. after a power-off mid-sleep) must NOT defer."""
	import json as _json
	import time as _time

	from red_pill.core import paths

	state_dir = tmp_path / "state"
	state_dir.mkdir()
	monkeypatch.setattr(paths, "get_state_dir", lambda: state_dir)

	register_driver(CountingDriver)
	job_id = queue.enqueue_task(source="test_counting", payload={"total": 1})

	status_file = state_dir / "sleep_phase_status.json"
	status_file.write_text(_json.dumps({"status": "running", "updated_at": _time.time()}))
	assert process_driver_jobs(queue) == 0
	task = queue.get_task(job_id)
	assert task["status"] == "PENDING" and task["attempts"] == 0

	# Stale heartbeat (machine died mid-sleep) -> the job runs normally.
	status_file.write_text(_json.dumps({"status": "running", "updated_at": _time.time() - 3600}))
	assert process_driver_jobs(queue) == 1


def test_resume_task_guards_live_processing(queue, clean_registry):
	"""resume_task recovers stale PROCESSING orphans but never a live job
	(fresh heartbeat) — that would double-execute it."""
	register_driver(CountingDriver)
	job_id = queue.enqueue_task(source="test_counting", payload={"total": 1})
	queue.pop_next_task(allowed_sources=["test_counting"])  # live PROCESSING

	assert queue.resume_task(job_id) is False
	assert queue.get_task(job_id)["status"] == "PROCESSING"

	with queue._get_connection() as conn:
		conn.execute("UPDATE cognitive_tasks SET updated_at = datetime('now', '-1 hour') WHERE id = ?", (job_id,))

	assert queue.resume_task(job_id) is True
	assert queue.get_task(job_id)["status"] == "PENDING"


def test_distill_preflight_resident_bypass_and_cold_boot_gate(monkeypatch):
	"""Resident LLM -> run without probing (free VRAM is low BECAUSE the model is
	loaded). Cold start -> defer unless there is headroom to boot the ephemeral."""
	from red_pill.core.vram_probe import VramProbe
	from red_pill.jobs.drivers.distill import DistillJobDriver
	from red_pill.metabolism import ephemeral_server

	driver = DistillJobDriver()

	monkeypatch.setattr(ephemeral_server, "_check_llm_available", lambda: True)
	monkeypatch.setattr(VramProbe, "get_free_mb", staticmethod(lambda: 100))
	driver.preflight({})  # resident: no probe, no raise

	monkeypatch.setattr(ephemeral_server, "_check_llm_available", lambda: False)
	with pytest.raises(JobDeferred):
		driver.preflight({})  # cold boot with 100MB free -> defer

	monkeypatch.setattr(VramProbe, "get_free_mb", staticmethod(lambda: 8000))
	driver.preflight({})  # cold boot with headroom -> proceed


def test_purge_hygiene_cleans_old_and_marks_stuck(queue, clean_registry):
	"""Nightly janitor hygiene: old COMPLETED/FRUSTRATED rows go away, stale
	PROCESSING becomes FRUSTRATED (dead-letter), and PENDING/PAUSED survive."""
	ids = {}
	for key, source, status, age in (
		("old_completed", "samantha", "COMPLETED", "-10 days"),
		("new_completed", "samantha", "COMPLETED", "-1 hour"),
		("old_frustrated", "drive_evaluator", "FRUSTRATED", "-30 days"),
		("stuck", "samantha", "PROCESSING", "-2 days"),
		("live", "samantha", "PROCESSING", "-1 minute"),
		("pending", "drive_evaluator", "PENDING", "-90 days"),
		("paused", "distill_job", "PAUSED", "-90 days"),
	):
		ids[key] = queue.enqueue_task(source=source, payload={})
		with queue._get_connection() as conn:
			conn.execute(
				"UPDATE cognitive_tasks SET status = ?, updated_at = datetime('now', ?) WHERE id = ?",
				(status, age, ids[key]),
			)

	result = queue.purge_hygiene(completed_days=7, frustrated_days=14, stale_processing_hours=24)

	assert result == {"completed_purged": 1, "frustrated_purged": 1, "stuck_marked": 1}
	assert queue.get_task(ids["old_completed"]) is None
	assert queue.get_task(ids["old_frustrated"]) is None
	assert queue.get_task(ids["new_completed"])["status"] == "COMPLETED"
	stuck = queue.get_task(ids["stuck"])
	assert stuck["status"] == "FRUSTRATED" and "queue_hygiene" in stuck["error_log"]
	assert queue.get_task(ids["live"])["status"] == "PROCESSING"
	assert queue.get_task(ids["pending"])["status"] == "PENDING"
	assert queue.get_task(ids["paused"])["status"] == "PAUSED"


def test_nightly_unit_active_defers_jobs(queue, clean_registry, monkeypatch):
	"""While redpill-sleep/redpill-chronicle systemd units are ACTIVE the runner
	yields (absolute priority for the 03:00/04:00 cycles), without attempts."""
	import subprocess as _sp

	class _Active:
		returncode = 0

	monkeypatch.setattr(_sp, "run", lambda *a, **kw: _Active())

	register_driver(CountingDriver)
	job_id = queue.enqueue_task(source="test_counting", payload={"total": 1})

	assert process_driver_jobs(queue) == 0
	task = queue.get_task(job_id)
	assert task["status"] == "PENDING" and task["attempts"] == 0
