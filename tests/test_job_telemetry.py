"""Telemetría F0 (NB-001): duración de etapas e instancias de fan-out en el
checkpoint del dag_job, y `durations` por fase en `sleep_phase_status.json`.

Instrumentación aditiva: no cambia comportamiento ni decisiones. Los minions
falsos duermen lo justo para que `time.monotonic()` avance de forma fiable.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock

from red_pill.jobs.drivers.dag import DagJobDriver


def _payload(workdir: str, stages, mission_id="m1", **extra):
	base = {"mission_id": mission_id, "manifest": {"workdir": workdir, "stages": stages}}
	base.update(extra)
	return base


def _patch_sleeping_factory(monkeypatch):
	"""Minions falsos que duermen 10 ms para que el cronómetro deje valor > 0."""

	class _Agent:
		async def execute(self, task, **kwargs):
			await asyncio.sleep(0.01)
			return {"status": "success", "response": "ok", "summary": "ok"}

	class _Command:
		async def execute(self, task, **kwargs):
			await asyncio.sleep(0.01)
			return {"status": "success", "returncode": 0, "stdout": "ok", "summary": "ok"}

	class _Source:
		def __init__(self, items):
			self._items = items

		async def execute(self, task, **kwargs):
			await asyncio.sleep(0.01)
			return {"status": "success", "returncode": 0, "summary": "ok", "items": self._items}

	def _create(minion_id, **kw):
		if minion_id == "source":
			return _Source(["a", "b", "c"])
		if minion_id == "agent":
			return _Agent()
		return _Command()

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(_create))
	monkeypatch.setattr("red_pill.jobs.drivers.dag_types.base._resolve_minion_kind", lambda mid: "agent" if mid == "agent" else "command")


def test_dag_checkpoint_records_stage_seconds(tmp_path, monkeypatch):
	"""P1.1: un dag mínimo deja `stage_seconds` por etapa con valor > 0."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch_sleeping_factory(monkeypatch)
	payload = _payload(
		str(ws),
		[
			{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "do X"},
			{"id": "smoke", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "smoke it", "depends_on": ["impl"]},
		],
	)
	o1 = d.step(payload, {})
	assert not o1.completed
	# La primera etapa ya deja su duración en el checkpoint (job aún en curso).
	assert "impl" in o1.new_checkpoint["stage_seconds"]
	assert o1.new_checkpoint["stage_seconds"]["impl"] > 0

	o2 = d.step(payload, o1.new_checkpoint)
	assert o2.completed
	assert set(o2.new_checkpoint["stage_seconds"]) == {"impl", "smoke"}
	assert all(v > 0 for v in o2.new_checkpoint["stage_seconds"].values())


def test_dag_fanout_records_item_seconds(tmp_path, monkeypatch):
	"""P1.2: una instancia de fan-out deja `item_seconds` (> 0), además de su `stage_seconds`."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch_sleeping_factory(monkeypatch)
	payload = _payload(
		str(ws),
		[
			{"id": "discover", "type": "command", "minion": "source", "command": "discover"},
			{
				"id": "plant",
				"type": "command",
				"minion": "command_runner",
				"fan_out_from": "discover",
				"depends_on": ["discover"],
				"command": "echo {{item}} > out.txt",
			},
		],
	)
	o1 = d.step(payload, {})
	o2 = d.step(payload, o1.new_checkpoint)
	assert o2.completed
	item_seconds = o2.new_checkpoint["item_seconds"]
	assert set(item_seconds) == {"plant/plant-0", "plant/plant-1", "plant/plant-2"}
	assert all(v > 0 for v in item_seconds.values())
	# Las instancias de fan-out también dejan su duración por etapa.
	for path in item_seconds:
		assert path in o2.new_checkpoint["stage_seconds"]


def test_sleep_phase_status_writes_durations_per_phase(monkeypatch, tmp_path):
	"""P1.3: `sleep_phase_status.json` escribe `durations` por fase (segundos)."""
	from red_pill.metabolism import sleep as sleep_mod
	from red_pill.metabolism.phases.base import SleepContext

	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: tmp_path)

	class _FakePhase:
		def __init__(self, name):
			self.name = name

		def execute(self, ctx):
			time.sleep(0.01)

	monkeypatch.setattr(sleep_mod, "SLEEP_PHASES", [_FakePhase("one"), _FakePhase("two")])

	ctx = SleepContext(memory_manager=MagicMock())
	sleep_mod.run_sleep_phase(ctx, 0)
	sleep_mod.run_sleep_phase(ctx, 1)

	data = json.loads((tmp_path / "sleep_phase_status.json").read_text(encoding="utf-8"))
	assert set(data["durations"]) == {"one", "two"}
	assert all(v > 0 for v in data["durations"].values())
