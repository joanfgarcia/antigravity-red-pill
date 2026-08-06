"""DagJobDriver (RFC_JOB_DAG_PARALLELIZATION): topología DAG, fan-out paralelo,
control transferible, validación en submit."""

import json
from pathlib import Path

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.jobs.drivers.dag import DagJobDriver


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


@pytest.fixture
def clean_registry():
	from red_pill.jobs.drivers import _REGISTRY

	saved = dict(_REGISTRY)
	_REGISTRY.clear()
	yield _REGISTRY
	_REGISTRY.clear()
	_REGISTRY.update(saved)


@pytest.fixture(autouse=True)
def silent_reports(monkeypatch):
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda *a, **kw: None)


def _payload(workdir: str, stages, mission_id="m1", **extra):
	base = {"mission_id": mission_id, "manifest": {"workdir": workdir, "stages": stages}}
	base.update(extra)
	return base


class _FakeBridge:
	def __init__(self, workdir, write_report=True):
		self.workdir = workdir
		self.write_report = write_report

	def health_check(self):
		return True

	def prompt(self, text, **kwargs):
		if self.write_report:
			import re

			m = re.search(r"to (\S+?) as JSON", text)
			if m:
				path = m.group(1)
				Path(path).parent.mkdir(parents=True, exist_ok=True)
				Path(path).write_text(json.dumps({"summary": "hecho"}), encoding="utf-8")
		return type("R", (), {"response": "ok", "error": None, "conversation_id": "c", "ok": True})()


def _patch_agentic(driver, monkeypatch, workdir):
	monkeypatch.setattr("red_pill.swarm.bridges.factory.create_bridge", lambda b=None, **kw: _FakeBridge(workdir))


def test_dag_validate_rejects_missing_mission():
	d = DagJobDriver()
	with pytest.raises(ValueError, match="mission_id"):
		d.validate({"manifest": {"workdir": "/tmp", "stages": [{"id": "a", "type": "agentic"}]}})
	with pytest.raises(ValueError, match="depends_on"):
		d.validate(_payload("/tmp", [{"id": "a", "type": "agentic", "depends_on": ["nope"]}]))
	with pytest.raises(ValueError, match="duplicate"):
		d.validate(_payload("/tmp", [{"id": "a", "type": "agentic"}, {"id": "a", "type": "agentic"}]))
	with pytest.raises(ValueError, match="type"):
		d.validate(_payload("/tmp", [{"id": "a", "type": "bogus"}]))


def test_dag_linear_agentic_runs_in_order(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch_agentic(d, monkeypatch, str(ws))
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agentic", "prompt": "do X"},
		{"id": "smoke", "type": "agentic", "prompt": "smoke it", "depends_on": ["impl"]},
	])
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	assert not o1.completed
	o2 = d.step(payload, o1.new_checkpoint)
	assert o2.completed
	assert o2.new_checkpoint["completed_stage_ids"] == ["impl", "smoke"]
	assert (ws / ".cell" / "reports" / "impl.json").is_file()


def test_dag_fanout_parallel_runs_all(tmp_path, monkeypatch):
	"""parallel: 3 lanza las 3 ramas en el mismo step (una etapa = todas o ninguna)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	real = _FakeBridge(str(ws))
	monkeypatch.setattr("red_pill.swarm.bridges.factory.create_bridge", lambda b=None, **kw: real)

	payload = _payload(str(ws), [
		{"id": "impl", "type": "agentic", "prompt": "do X"},
		{"id": "lens", "type": "agentic", "prompt": "lens", "depends_on": ["impl"], "parallel": 3},
	])
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	o2 = d.step(payload, o1.new_checkpoint)
	# el fan-out (parallel 3 pero una sola etapa id 'lens') completa la etapa única
	assert o2.completed
	assert o2.new_checkpoint["completed_stage_ids"] == ["impl", "lens"]


def test_dag_parallel_fanout_multi(tmp_path, monkeypatch):
	"""Varias etapas independientes en el frente se ejecutan juntas (max_concurrency)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch_agentic(d, monkeypatch, str(ws))
	payload = _payload(str(ws), [
		{"id": "a", "type": "agentic", "prompt": "a"},
		{"id": "b", "type": "agentic", "prompt": "b"},
		{"id": "c", "type": "agentic", "prompt": "c", "depends_on": ["a", "b"]},
	], max_concurrency=2)
	o1 = d.step(payload, {})
	assert set(o1.new_checkpoint["completed_stage_ids"]) == {"a", "b"}
	o2 = d.step(payload, o1.new_checkpoint)
	assert o2.completed and o2.new_checkpoint["completed_stage_ids"] == ["a", "b", "c"]


def test_dag_script_stage(tmp_path):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	payload = _payload(str(ws), [
		{"id": "gen", "type": "script", "command": "echo hi > gen.txt"},
	])
	o = d.step(payload, {})
	assert o.completed
	assert (ws / "gen.txt").is_file()
	assert o.new_checkpoint["results"]["gen"] == "gen: ok"


def test_dag_on_fail_stop_raises(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)

	class _Broken(_FakeBridge):
		def prompt(self, text, **kwargs):
			return type("R", (), {"response": "", "error": "boom", "conversation_id": "x", "ok": False})()

	monkeypatch.setattr("red_pill.swarm.bridges.factory.create_bridge", lambda b=None, **kw: _Broken(str(ws)))
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agentic", "prompt": "x", "on_fail": "stop"},
	])
	with pytest.raises(RuntimeError, match="on_fail=stop"):
		d.step(payload, {})


def test_dag_on_fail_warn_continues(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)

	class _Broken(_FakeBridge):
		def prompt(self, text, **kwargs):
			return type("R", (), {"response": "", "error": "boom", "conversation_id": "x", "ok": False})()

	monkeypatch.setattr("red_pill.swarm.bridges.factory.create_bridge", lambda b=None, **kw: _Broken(str(ws)))
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agentic", "prompt": "x", "on_fail": "warn"},
	])
	o = d.step(payload, {})
	assert o.completed
	assert "FAILED" in o.new_checkpoint["results"]["impl"]


def test_dag_transferable_control(tmp_path, monkeypatch):
	"""Control transferible: un checkpoint escrito desde fuera (handoff) se respeta."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch_agentic(d, monkeypatch, str(ws))
	payload = _payload(str(ws), [
		{"id": "a", "type": "agentic", "prompt": "a"},
		{"id": "b", "type": "agentic", "prompt": "b", "depends_on": ["a"]},
	])
	# el main-loop tomó el control y ejecutó 'a' inline
	handoff = {"completed_stage_ids": ["a"], "results": {"a": "hecho-inline"}}
	o = d.step(payload, handoff)
	assert o.completed
	assert o.new_checkpoint["completed_stage_ids"] == ["a", "b"]
	assert o.new_checkpoint["results"]["a"] == "hecho-inline"


def test_dag_status_file(tmp_path, monkeypatch):
	"""Telemetría pública (espejo)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch_agentic(d, monkeypatch, str(ws))
	payload = _payload(str(ws), [{"id": "a", "type": "agentic", "prompt": "a"}])
	d.step(payload, {})
	status = json.loads((ws / ".cell" / "dag_status.json").read_text())
	assert status["completed"] == 1 and status["total"] == 1
	assert status["status"] == "completed"
