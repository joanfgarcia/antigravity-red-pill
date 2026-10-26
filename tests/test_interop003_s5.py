"""RFC-INTEROP-003 S5 — cierre con identidad y artefactos."""

from __future__ import annotations

import json
import uuid

import red_pill.jobs.artifacts as artifacts
from red_pill.core.inbox import MinionInbox

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"


def _task(tmp_path, *, continuity=CID):
	return {
		"id": f"job-{uuid.uuid4().hex}",
		"source": "dag_job",
		"status": "COMPLETED",
		"mission_id": "forge:s5",
		"continuity_id": continuity,
		"parent_mission_id": "repo:next" if continuity else None,
		"checkpoint_data": {
			"continuity_id": continuity,
			"parent_mission_id": "repo:next" if continuity else None,
			"originator": "dag:test" if continuity else "",
			"role": "job" if continuity else "",
		},
		"payload": {"manifest": {"workdir": str(tmp_path)}},
	}


def test_result_json_has_identity_and_workspace_artifact(tmp_path, monkeypatch):
	monkeypatch.setattr(artifacts, "get_state_dir", lambda: tmp_path / "state")
	task = _task(tmp_path)
	result = artifacts.write_job_result(task, status="success", summary="todo bien")

	state_file = tmp_path / "state" / "jobs" / "results" / f"{task['id']}.json"
	assert state_file.is_file()
	payload = json.loads(state_file.read_text())
	assert payload["continuity_id"] == CID
	assert payload["parent_mission_id"] == "repo:next"
	assert payload["originator"] == "dag:test"
	assert payload["status"] == "success"

	workspace = tmp_path / ".red-pill" / "memory" / "jobs"
	assert (workspace / f"{task['id']}.json").is_file()
	notes = (workspace / f"{task['id']}.md").read_text()
	assert CID in notes and "todo bien" in notes
	assert result["paths"]["state_json"] == str(state_file)


def test_result_without_soul_does_not_invent_identity(tmp_path, monkeypatch):
	monkeypatch.setattr(artifacts, "get_state_dir", lambda: tmp_path / "state")
	task = _task(tmp_path, continuity=None)
	result = artifacts.write_job_result(task, status="failed", summary="boom", error="exit 1")
	assert result["continuity_id"] is None
	assert result["parent_mission_id"] is None
	assert result["error"] == "exit 1"


def test_inbox_persists_continuity(tmp_path):
	inbox = MinionInbox(str(tmp_path / "inbox.db"))
	inbox.drop_report(
		event_id="abcd1234",
		source="JobRunner",
		status="success",
		content="done",
		originator="dag:test",
		continuity_id=CID,
	)
	reports = inbox.get_unread()
	assert reports[0]["continuity_id"] == CID
	assert reports[0]["originator"] == "dag:test"

	popped = inbox.pop_unread()
	assert popped[0]["continuity_id"] == CID


def test_report_job_production_path(tmp_path, monkeypatch):
	import red_pill.core.inbox as inbox_mod
	from red_pill.core.queue_worker import _report_job

	monkeypatch.setattr(artifacts, "get_state_dir", lambda: tmp_path / "state")
	seen = {}

	class FakeInbox:
		def drop_report(self, **kwargs):
			seen.update(kwargs)

	monkeypatch.setattr(inbox_mod, "MinionInbox", FakeInbox)
	task = _task(tmp_path)
	_report_job(task["id"], task, "success", "ok")
	assert seen["continuity_id"] == CID
	assert seen["originator"] == "dag:test"
	assert (tmp_path / "state" / "jobs" / "results" / f"{task['id']}.json").is_file()


def test_result_respects_custom_memory_path_and_relative_workdir(tmp_path, monkeypatch):
	import red_pill.core.workspaces as ws_mod

	workdir = tmp_path / "repo"
	workdir.mkdir()
	memory = tmp_path / "custom-memory"
	monkeypatch.setattr(artifacts, "get_state_dir", lambda: tmp_path / "state")

	class FakeWorkspace:
		@property
		def get_memory_path(self):
			return memory

	monkeypatch.setattr(ws_mod, "find_workspace", lambda _path: FakeWorkspace())
	task = _task(workdir)
	task["payload"] = {"cwd": str(tmp_path), "manifest": {"workdir": "repo"}}
	artifacts.write_job_result(task, status="success", summary="ok")
	assert (memory / "jobs" / f"{task['id']}.json").is_file()
	assert not (workdir / ".red-pill" / "memory" / "jobs").exists()
