"""Techo de pared por compuesto (NB-001 F3, D-NB-01/02/07/12/13).

El deadline se declara por compuesto (`deadline_minutes`, o `control.deadline_minutes`
por compuesto), se ancla en el primer step del compuesto (`stage_deadline_ts`),
persistido en el checkpoint, y SOLO corta fan-out: agotado, las instancias
pendientes se difieren con `JobDeferred("budget_exhausted")` + contador
`deferred_by_budget`. Las etapas no-fanout (la cola del sueño) nunca se difieren.
Flag `JOB_COMPOUND_DEADLINE_ENABLED` (default False): OFF → comportamiento exacto.
"""

import time as _time

import pytest

from red_pill.jobs.drivers.base import JobDeferred
from red_pill.jobs.drivers.dag import DagJobDriver
from red_pill.jobs.drivers.dag_manifest import clamp_deadline_minutes


def _payload(workdir, stages, mission_id="m1", **extra):
	base = {"mission_id": mission_id, "manifest": {"workdir": workdir, "stages": stages}}
	base.update(extra)
	return base


def _patch_fanout_factory(monkeypatch, record, items):
	"""Minion `source` que devuelve `items`; `command_runner` devuelve éxito."""

	class _FakeSource:
		async def execute(self, task, **kwargs):
			record.append((task, kwargs))
			return {"status": "success", "returncode": 0, "summary": "ok", "items": list(items)}

	class _FakeCommand:
		async def execute(self, task, **kwargs):
			record.append((task, kwargs))
			return {"status": "success", "returncode": 0, "stdout": "ok", "summary": "ok"}

	def _create(minion_id, **kw):
		if minion_id == "source":
			return _FakeSource()
		if minion_id == "command_runner":
			return _FakeCommand()
		raise KeyError(minion_id)

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(_create))


def _deadline_manifest():
	"""discover → 6 items · plant (fan-out stepwise, techo 60 s) · finalize (no-fanout)."""
	return [
		{"id": "discover", "type": "command", "minion": "source", "command": "discover"},
		{
			"id": "plant",
			"type": "command",
			"minion": "command_runner",
			"fan_out_from": "discover",
			"depends_on": ["discover"],
			"fanout_stepwise": True,
			"deadline_minutes": 1,  # 60 s de techo para el fan-out del compuesto
			"command": "echo {{item}}",
		},
		{"id": "finalize", "type": "command", "minion": "command_runner", "command": "finalize", "depends_on": ["plant"]},
	]


def _enable_deadline(monkeypatch):
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "JOB_COMPOUND_DEADLINE_ENABLED", True)
	return cfg


def test_compound_deadline_defers_fanout_only(tmp_path, monkeypatch):
	"""P5.1/P5.2/P5.3: 6 items de 30 s con techo 60 s → 3 hechos, 3 diferidos;
	el checkpoint marca los 3 diferidos; el job NO reentra para seguirlos; la
	cola no-fanout (finalize) SÍ corre y el job completa."""
	_enable_deadline(monkeypatch)
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_fanout_factory(monkeypatch, calls, ["i0", "i1", "i2", "i3", "i4", "i5"])
	payload = _payload(str(ws), _deadline_manifest())

	# Reloj de pared controlado: cada instancia de fan-out avanza 30 s.
	clock = {"t": 1000.0}
	monkeypatch.setattr(_time, "time", lambda: clock["t"])

	real_run = d._run_atomic

	def _slow(payload_, stage_, path_, gate_=None):
		if stage_.get("_item") is not None:
			clock["t"] += 30.0
		return real_run(payload_, stage_, path_, gate_)

	monkeypatch.setattr(d, "_run_atomic", _slow)

	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["discover"]

	o2 = d.step(payload, o1.new_checkpoint)
	assert "plant/plant-0" in o2.new_checkpoint["completed_stage_ids"]
	assert o2.new_checkpoint["stage_deadline_ts"]["plant"] == 1000.0  # anclado en el primer step

	o3 = d.step(payload, o2.new_checkpoint)
	assert "plant/plant-1" in o3.new_checkpoint["completed_stage_ids"]

	o4 = d.step(payload, o3.new_checkpoint)
	assert "plant/plant-2" in o4.new_checkpoint["completed_stage_ids"]

	# t = 1090 > 1000 + 60 → el techo se agota: se cierra el frente con deferral.
	with pytest.raises(JobDeferred) as exc:
		d.step(payload, o4.new_checkpoint)
	assert exc.value.reason == "budget_exhausted"
	ckpt = exc.value.checkpoint
	assert ckpt["deferred_by_budget"] == 3
	assert set(ckpt["deferred_stage_ids"]) == {"plant/plant-3", "plant/plant-4", "plant/plant-5"}
	assert "plant" in ckpt["completed_stage_ids"]  # compuesto de fan-out cerrado

	# P5.2: reentrada → NO se ejecutan los diferidos (distinto de ceder).
	# P5.3: la cola no-fanout (finalize) SÍ corre y el job completa.
	o6 = d.step(payload, ckpt)
	assert o6.completed
	assert "finalize" in o6.new_checkpoint["completed_stage_ids"]
	echo_calls = [t for t, _ in calls if t.startswith("echo ")]
	assert len(echo_calls) == 3  # solo 3 instancias ejecutadas, 3 diferidas
	assert o6.new_checkpoint["deferred_by_budget"] == 3
	assert set(o6.new_checkpoint["deferred_stage_ids"]) == {"plant/plant-3", "plant/plant-4", "plant/plant-5"}


def test_deadline_minutes_clamp():
	"""P5.4: clamp [0, 720]; 0/negativo/ausente/no-numérico = sin techo."""
	assert clamp_deadline_minutes(6000000) == 720
	assert clamp_deadline_minutes(720) == 720
	assert clamp_deadline_minutes(0) == 0
	assert clamp_deadline_minutes(-5) == 0
	assert clamp_deadline_minutes(None) == 0
	assert clamp_deadline_minutes("bogus") == 0
	assert clamp_deadline_minutes(30) == 30


def test_flag_off_is_exact_current_behavior(tmp_path, monkeypatch):
	"""P5.6: flag en False (default) → el techo se ignora y corren los 6 items."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_fanout_factory(monkeypatch, calls, ["i0", "i1", "i2", "i3", "i4", "i5"])
	payload = _payload(str(ws), _deadline_manifest())

	ckpt = {}
	outcome = None
	for _ in range(20):
		outcome = d.step(payload, ckpt)
		ckpt = outcome.new_checkpoint
		if outcome.completed:
			break
	assert outcome is not None and outcome.completed
	assert len([t for t, _ in calls if t.startswith("echo ")]) == 6
	assert "deferred_by_budget" not in ckpt
	assert "deferred_stage_ids" not in ckpt
	assert "stage_deadline_ts" not in ckpt


def test_zero_deadline_means_no_ceiling(tmp_path, monkeypatch):
	"""deadline_minutes=0 (o negativo) con el flag ON → sin techo, corren los 6."""
	_enable_deadline(monkeypatch)
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_fanout_factory(monkeypatch, calls, ["i0", "i1", "i2", "i3", "i4", "i5"])
	stages = _deadline_manifest()
	stages[1]["deadline_minutes"] = 0
	payload = _payload(str(ws), stages)

	ckpt = {}
	outcome = None
	for _ in range(20):
		outcome = d.step(payload, ckpt)
		ckpt = outcome.new_checkpoint
		if outcome.completed:
			break
	assert outcome is not None and outcome.completed
	assert len([t for t, _ in calls if t.startswith("echo ")]) == 6
	assert "deferred_by_budget" not in ckpt


def test_control_deadline_minutes_mapping(tmp_path, monkeypatch):
	"""`control.deadline_minutes` por compuesto (D-NB-12) corta igual que el campo directo."""
	_enable_deadline(monkeypatch)
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_fanout_factory(monkeypatch, calls, ["i0", "i1", "i2", "i3", "i4", "i5"])
	stages = _deadline_manifest()
	del stages[1]["deadline_minutes"]
	payload = _payload(str(ws), stages, control={"deadline_minutes": {"plant": 1}})

	clock = {"t": 1000.0}
	monkeypatch.setattr(_time, "time", lambda: clock["t"])
	real_run = d._run_atomic

	def _slow(payload_, stage_, path_, gate_=None):
		if stage_.get("_item") is not None:
			clock["t"] += 30.0
		return real_run(payload_, stage_, path_, gate_)

	monkeypatch.setattr(d, "_run_atomic", _slow)

	ckpt = {}
	for _ in range(4):
		ckpt = d.step(payload, ckpt).new_checkpoint
	with pytest.raises(JobDeferred) as exc:
		d.step(payload, ckpt)
	assert exc.value.reason == "budget_exhausted"
	assert exc.value.checkpoint["deferred_by_budget"] == 3
