"""RFC-INTEROP-003 S4 — mando, lease de misión y autorización."""

from __future__ import annotations

import json
import uuid

import pytest

import red_pill.mcp_server as mcp
from red_pill.jobs.drivers.dag import DagJobDriver
from red_pill.session.lease import LeaseStore

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"
OTHER = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857e"


def _mission() -> str:
	return f"mission:s4-{uuid.uuid4().hex[:12]}"


def _payload(tmp_path, mission: str, continuity: str | None = CID):
	payload = {
		"mission_id": "forge:x",
		"parent_mission_id": mission,
		"role": "job",
		"manifest": {
			"workdir": str(tmp_path),
			"stages": [{"id": "a", "type": "command", "minion": "command_runner", "command": "echo a"}],
		},
	}
	if continuity:
		payload["continuity_id"] = continuity
	return payload


def _fake_minion(monkeypatch):
	import red_pill.swarm.factory as factory_mod

	class Fake:
		async def execute(self, task, **kwargs):
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr(factory_mod.MinionFactory, "create", lambda name: Fake())


def test_job_observes_and_closes_soul_lease(tmp_path, monkeypatch):
	_fake_minion(monkeypatch)
	mission = _mission()
	leases = LeaseStore()
	driver = DagJobDriver()
	driver.job_id = f"job-{uuid.uuid4().hex[:8]}"
	leases.begin_mission_lease(mission, continuity_id=CID, holder_originator="", owner_kind="soul", metadata={"job_id": driver.job_id})
	driver.step_timeout_s = 60
	driver._step_started = None
	cp = driver.begin_step(_payload(tmp_path, mission), {})
	lease = leases.active_mission_lease(mission)
	assert lease and lease["continuity_id"] == CID and lease["owner_kind"] == "soul"
	driver.on_terminal(_payload(tmp_path, mission), cp, "completed")
	assert leases.get(f"mission:{mission}")["state"] == "completed"


def test_job_does_not_steal_other_soul_lease(tmp_path, monkeypatch):
	_fake_minion(monkeypatch)
	mission = _mission()
	leases = LeaseStore()
	leases.begin_mission_lease(mission, continuity_id=OTHER, holder_originator="", owner_kind="soul")
	driver = DagJobDriver()
	driver.job_id = f"job-{uuid.uuid4().hex[:8]}"
	driver.step_timeout_s = 60
	driver._step_started = None
	cp = driver.begin_step(_payload(tmp_path, mission), {})
	assert cp["parent_mission_id"] == mission
	assert leases.active_mission_lease(mission)["continuity_id"] == OTHER
	driver.on_terminal(_payload(tmp_path, mission), cp, "completed")
	assert leases.get(f"mission:{mission}")["state"] == "active"
	leases.finish(f"mission:{mission}", state="completed", reason="test-cleanup")


def test_mission_lease_is_optional_without_soul(tmp_path, monkeypatch):
	_fake_minion(monkeypatch)
	mission = _mission()
	driver = DagJobDriver()
	driver.job_id = f"job-{uuid.uuid4().hex[:8]}"
	driver.step_timeout_s = 60
	driver._step_started = None
	cp = driver.begin_step(_payload(tmp_path, mission, continuity=None), {})
	assert "continuity_id" not in cp
	assert LeaseStore().active_mission_lease(mission) is None


def test_job_without_lease_does_not_create_one(tmp_path, monkeypatch):
	_fake_minion(monkeypatch)
	mission = _mission()
	driver = DagJobDriver()
	driver.job_id = f"job-{uuid.uuid4().hex[:8]}"
	driver.step_timeout_s = 60
	driver._step_started = None
	driver.begin_step(_payload(tmp_path, mission), {})
	assert LeaseStore().active_mission_lease(mission) is None


def _task(mission: str, continuity: str | None = CID):
	return {
		"id": f"job-{uuid.uuid4().hex[:8]}",
		"source": "dag_job",
		"status": "PAUSED",
		"continuity_id": continuity,
		"parent_mission_id": mission,
		"checkpoint_data": {
			"continuity_id": continuity,
			"parent_mission_id": mission,
			"originator": "dag:test",
			"role": "job",
		},
		"payload": {},
	}


@pytest.mark.asyncio
async def test_other_soul_cannot_transfer(monkeypatch):
	mission = _mission()
	task = _task(mission)

	async def other_session(_args):
		return {"continuity_id": OTHER}

	monkeypatch.setattr(mcp, "_caller_session", other_session)
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	denied = await mcp._authorize_job_mutation(task, "job_transfer")
	assert denied and "otra alma" in denied


@pytest.mark.asyncio
async def test_owner_and_operator_can_transfer(monkeypatch):
	mission = _mission()
	task = _task(mission)

	async def owner_session(_args):
		return {"continuity_id": CID}

	monkeypatch.setattr(mcp, "_caller_session", owner_session)
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
	assert await mcp._authorize_job_mutation(task, "job_transfer") is None
	monkeypatch.setenv("REDPILL_OPERATOR", "1")
	assert await mcp._authorize_job_mutation(_task(mission), "job_transfer") is None
	monkeypatch.delenv("REDPILL_OPERATOR", raising=False)


@pytest.mark.asyncio
async def test_no_soul_job_keeps_legacy_control(monkeypatch):
	task = _task(_mission(), continuity=None)

	async def no_session(_args):
		return {}

	monkeypatch.setattr(mcp, "_caller_session", no_session)
	assert await mcp._authorize_job_mutation(task, "job_kill") is None


@pytest.mark.asyncio
async def test_transfer_returns_identity_and_blocks_split_brain(monkeypatch):
	mission = _mission()
	task = _task(mission)
	state = {"task": task}

	class FakeQueue:
		def get_task(self, ref):
			return state["task"]

		def pause_task(self, job_id):
			return True

	monkeypatch.setattr(mcp, "_queue", lambda: FakeQueue())
	monkeypatch.setattr(mcp, "_resolve_job", lambda qm, ref: qm.get_task(ref))

	async def owner_session(_args):
		return {"continuity_id": CID}

	monkeypatch.setattr(mcp, "_caller_session", owner_session)
	out = await mcp.handle_job_transfer({"job_id": task["id"]})
	data = json.loads(out[0].text)
	assert data["continuity_id"] == CID
	assert data["parent_mission_id"] == mission
	assert data["originator"] == "dag:test"

	leases = LeaseStore()
	leases.finish(f"mission:{mission}", state="completed", reason="test-cleanup")
	leases.begin_mission_lease(mission, continuity_id=OTHER, holder_originator="", owner_kind="soul")
	error = mcp._ensure_job_mission_lease(_task(mission))
	assert error and "split-brain" in error
	leases.finish(f"mission:{mission}", state="completed", reason="test-cleanup")


def test_checkpoint_cannot_inject_foreign_identity():
	task = _task(_mission())
	clean, error = mcp._sanitize_job_checkpoint(task, {"parent_mission_id": "repo:victima"})
	assert clean is None and error and "no coincide" in error
	clean, error = mcp._sanitize_job_checkpoint(task, {"continuity_id": OTHER})
	assert clean is None and error and "no coincide" in error
	clean, error = mcp._sanitize_job_checkpoint(task, {"step_index": 2})
	assert error is None and clean == {"step_index": 2}


def test_no_soul_job_cannot_inject_identity():
	task = _task(_mission(), continuity=None)
	clean, error = mcp._sanitize_job_checkpoint(task, {"continuity_id": CID})
	assert clean is None and error and "sin alma" in error


def test_kill_task_ex_reports_previous_processing_status(tmp_path):
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	qm = CognitiveQueueManager(str(tmp_path / "queue.db"))
	job_id = qm.enqueue_task(source="dag_job", payload={"title": "t"})
	assert qm.pop_next_task(allowed_sources=["dag_job"])["id"] == job_id
	killed, previous = qm.kill_task_ex(job_id)
	assert killed is True and previous == "PROCESSING"
	assert qm.get_task(job_id)["status"] == "PAUSED"


def test_completed_cannot_resurrect_frustrated_job(tmp_path):
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	qm = CognitiveQueueManager(str(tmp_path / "queue.db"))
	job_id = qm.enqueue_task(source="dag_job", payload={"title": "t"})
	qm.pop_next_task(allowed_sources=["dag_job"])
	qm.kill_task_ex(job_id, discard=True)
	qm.mark_completed(job_id)
	assert qm.get_task(job_id)["status"] == "FRUSTRATED"


def test_completed_cannot_overwrite_paused_dirty_kill(tmp_path):
	from red_pill.cognitive.queue_manager import CognitiveQueueManager

	qm = CognitiveQueueManager(str(tmp_path / "queue.db"))
	job_id = qm.enqueue_task(source="dag_job", payload={"title": "t"})
	qm.pop_next_task(allowed_sources=["dag_job"])
	qm.kill_task_ex(job_id, discard=False)
	qm.mark_completed(job_id)
	task = qm.get_task(job_id)
	assert task["status"] == "PAUSED"
	assert task["checkpoint_data"]["dirty_kill"]
