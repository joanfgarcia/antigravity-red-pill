"""RFC-INTEROP-003 S0/S1 — identidad de alma en dag_job."""

from __future__ import annotations

import sqlite3

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.jobs.drivers.dag import DagJobDriver
from red_pill.jobs.drivers.dag_validate import validate_payload

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"


def _payload(**extra):
	base = {
		"mission_id": "forge:x",
		"manifest": {"workdir": ".", "stages": [{"id": "a", "type": "command", "minion": "command_runner", "command": "echo a"}]},
	}
	base.update(extra)
	return base


def test_dag_identity_validation():
	validate_payload(_payload(continuity_id=CID, parent_mission_id="repo:next", role="job"))
	with pytest.raises(ValueError):
		validate_payload(_payload(continuity_id="no-uuid"))
	with pytest.raises(ValueError):
		validate_payload(_payload(parent_mission_id="sin-scope"))
	with pytest.raises(ValueError):
		validate_payload(_payload(role="root"))


def test_queue_has_identity_columns(tmp_path):
	qm = CognitiveQueueManager(str(tmp_path / "queue.db"))
	task_id = qm.enqueue_task(
		source="dag_job",
		payload=_payload(continuity_id=CID, parent_mission_id="repo:next"),
		mission_id="forge:x",
	)
	con = sqlite3.connect(qm.db_path)
	row = con.execute(
		"SELECT continuity_id, parent_mission_id FROM cognitive_tasks WHERE id=?", (task_id,)
	).fetchone()
	con.close()
	assert row == (CID, "repo:next")


def test_dag_checkpoint_has_identity():
	driver = DagJobDriver()
	driver.job_id = "job-123"
	payload = {"continuity_id": CID, "parent_mission_id": "repo:next", "role": "job"}
	identity = driver._identity_fields(payload, {})
	assert identity == {
		"continuity_id": CID,
		"originator": "dag:job-123",
		"role": "job",
		"parent_mission_id": "repo:next",
	}


def test_command_stage_receives_identity_env(tmp_path, monkeypatch):
	import red_pill.swarm.factory as factory_mod

	seen = {}

	class FakeMinion:
		async def execute(self, task, **kwargs):
			seen.update(kwargs)
			seen["task"] = task
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr(factory_mod.MinionFactory, "create", lambda name: FakeMinion())
	driver = DagJobDriver()
	driver.job_id = "job-123"
	driver.step_timeout_s = 60
	driver._step_started = None
	payload = _payload(continuity_id=CID, parent_mission_id="repo:next", role="job")
	payload["manifest"]["workdir"] = str(tmp_path)
	stage = {"id": "a", "type": "command", "minion": "command_runner", "command": "echo hi"}
	driver._run_atomic(payload, stage, "a")
	assert seen["continuity_id"] == CID
	assert seen["role"] == "job"
	assert seen["env"]["REDPILL_CONTINUITY_ID"] == CID
	assert seen["env"]["REDPILL_PARENT_MISSION_ID"] == "repo:next"


def test_agent_stage_prompt_gets_identity_block(tmp_path, monkeypatch):
	import red_pill.swarm.factory as factory_mod

	seen = {}

	class FakeMinion:
		async def execute(self, task, **kwargs):
			seen["task"] = task
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr(factory_mod.MinionFactory, "create", lambda name: FakeMinion())
	driver = DagJobDriver()
	driver.job_id = "job-123"
	driver.step_timeout_s = 60
	driver._step_started = None
	payload = _payload(continuity_id=CID, parent_mission_id="repo:next")
	payload["manifest"]["workdir"] = str(tmp_path)
	stage = {"id": "a", "type": "agent", "minion": "agent", "backend": "local", "prompt": "hazlo"}
	driver._run_atomic(payload, stage, "a")
	assert "<redpill-identity>" in seen["task"]
	assert f"continuity_id: {CID}" in seen["task"]


def test_uuidv4_is_rejected_and_stage_identity_is_validated():
	import uuid

	with pytest.raises(ValueError):
		validate_payload(_payload(continuity_id=str(uuid.uuid4())))
	bad = _payload()
	bad["manifest"]["stages"][0]["role"] = "root"
	with pytest.raises(ValueError):
		validate_payload(bad)


def test_checkpoint_continuity_cannot_change_mid_job():
	driver = DagJobDriver()
	driver.job_id = "j1"
	with pytest.raises(ValueError):
		driver._identity_fields({"continuity_id": CID}, {"continuity_id": "01a1728b-8cc4-7cf8-a9e2-f110b1b5857e"})


def test_command_env_has_mission_and_job(tmp_path, monkeypatch):
	import red_pill.swarm.factory as factory_mod

	seen = {}

	class FakeMinion:
		async def execute(self, task, **kwargs):
			seen.update(kwargs)
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr(factory_mod.MinionFactory, "create", lambda name: FakeMinion())
	driver = DagJobDriver()
	driver.job_id = "job-xyz"
	driver.step_timeout_s = 60
	driver._step_started = None
	payload = _payload(continuity_id=CID, parent_mission_id="repo:next")
	payload["manifest"]["workdir"] = str(tmp_path)
	stage = {"id": "a", "type": "command", "minion": "command_runner", "command": "echo hi"}
	driver._run_atomic(payload, stage, "a")
	assert seen["mission_id"] == "forge:x"
	assert seen["job_id"] == "job-xyz"
	assert seen["env"]["REDPILL_MISSION_ID"] == "forge:x"
	assert seen["env"]["REDPILL_JOB_ID"] == "job-xyz"


def test_stage_params_cannot_override_identity(tmp_path, monkeypatch):
	import red_pill.swarm.factory as factory_mod

	class FakeMinion:
		async def execute(self, task, **kwargs):
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr(factory_mod.MinionFactory, "create", lambda name: FakeMinion())
	driver = DagJobDriver()
	driver.job_id = "j1"
	driver.step_timeout_s = 60
	driver._step_started = None
	payload = _payload(continuity_id=CID)
	payload["manifest"]["workdir"] = str(tmp_path)
	stage = {"id": "a", "type": "command", "minion": "command_runner", "command": "echo", "params": {"continuity_id": "evil"}}
	with pytest.raises(ValueError):
		driver._run_atomic(payload, stage, "a")
