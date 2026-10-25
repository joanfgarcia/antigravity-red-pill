"""RFC-INTEROP-003 S2/S3 — leg del job, eventos y descubrimiento."""

from __future__ import annotations

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.jobs.drivers.dag import DagJobDriver
from red_pill.session.store import SessionRegistry

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"


def _payload(tmp_path):
	return {
		"mission_id": "forge:x",
		"continuity_id": CID,
		"parent_mission_id": "mission:test",
		"role": "job",
		"manifest": {
			"workdir": str(tmp_path),
			"stages": [
				{"id": "a", "type": "command", "minion": "command_runner", "command": "echo a"},
				{"id": "b", "type": "command", "minion": "command_runner", "command": "echo b", "depends_on": ["a"]},
			],
		},
	}


def _fake_minion(monkeypatch):
	import red_pill.swarm.factory as factory_mod

	class Fake:
		async def execute(self, task, **kwargs):
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr(factory_mod.MinionFactory, "create", lambda name: Fake())


def test_job_leg_and_events(tmp_path, monkeypatch):
	_fake_minion(monkeypatch)
	registry = SessionRegistry()
	driver = DagJobDriver()
	driver.job_id = "job-s2"
	driver.step_timeout_s = 60
	driver._step_started = None
	payload = _payload(tmp_path)
	cp = driver.begin_step(payload, {})
	leg = registry.get_by_originator("dag:job-s2")
	assert leg and leg["continuity_id"] == CID and leg["role"] == "job"

	out = driver.step(payload, cp)
	assert out.completed is False  # queda b
	events = registry.fetch_events("mission:test")
	assert any(e["type"] == "phase_done" and e["ref"] == "job-s2" for e in events)

	out = driver.step(payload, out.new_checkpoint)
	assert out.completed is True
	driver.on_terminal(payload, out.new_checkpoint, "completed")
	leg = registry.get_by_originator("dag:job-s2")
	assert leg["ttl_state"] == "expired"
	events = registry.fetch_events("mission:test")
	assert any(e["type"] == "mission_closed" and e["ref"] == "job-s2" for e in events)


def test_job_list_filters_by_continuity(tmp_path):
	qm = CognitiveQueueManager(str(tmp_path / "queue.db"))
	t1 = qm.enqueue_task(source="dag_job", payload={"continuity_id": CID}, mission_id="m")
	qm.enqueue_task(source="dag_job", payload={"continuity_id": "01a1728b-8cc4-7cf8-a9e2-f110b1b5857e"}, mission_id="m")
	rows = qm.list_tasks(continuity_id=CID)
	assert [r["id"] for r in rows] == [t1]
