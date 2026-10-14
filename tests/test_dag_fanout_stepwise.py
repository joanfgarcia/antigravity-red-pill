"""Fan-out `fanout_stepwise`: 1 item = 1 step → progreso visible (RFC-JOBDAG-002).

Sin el flag, el driver corre TODO el frente en un step (el contador salta de un
50% a un 100% y queda congelado mientras corre). Con `fanout_stepwise`, las
instancias se encadenan (i depende de i-1) → el frente tiene UNA a la vez → el
progreso del job avanza por item.
"""

from __future__ import annotations

from pathlib import Path

from red_pill.jobs.drivers.dag import DagJobDriver


def _fake_factory(monkeypatch):
	import red_pill.swarm.factory as fac

	class _Cmd:
		async def execute(self, task, **kwargs):
			return {"status": "success", "returncode": 0, "stdout": "ok", "summary": "ok"}

	class _Src:
		async def execute(self, task, **kwargs):
			return {"status": "success", "returncode": 0, "items": ["a", "b", "c"], "stdout": "ok", "summary": "ok"}

	def _create(minion_id, **kw):
		return _Src() if minion_id == "source" else _Cmd()

	monkeypatch.setattr(fac.MinionFactory, "create", staticmethod(_create))
	monkeypatch.setattr("red_pill.jobs.drivers.dag_types.base._resolve_minion_kind", lambda mid: "command")


def _payload(ws: str, stepwise: bool):
	plant = {
		"id": "plant",
		"type": "command",
		"minion": "command_runner",
		"fan_out_from": "discover",
		"depends_on": ["discover"],
		"command": "echo {{item}}",
	}
	if stepwise:
		plant["fanout_stepwise"] = True
		plant["fanout_label"] = "sesión"
	return {
		"mission_id": "m",
		"manifest": {
			"workdir": ws,
			"stages": [
				{"id": "discover", "type": "command", "minion": "source", "command": "discover"},
				plant,
			],
		},
	}


def test_stepwise_una_instancia_por_step(tmp_path, monkeypatch):
	_fake_factory(monkeypatch)
	(Path(tmp_path) / ".cell" / "reports").mkdir(parents=True)
	d = DagJobDriver()
	payload = _payload(str(tmp_path), stepwise=True)

	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["discover"]

	o2 = d.step(payload, o1.new_checkpoint)
	ids2 = o2.new_checkpoint["completed_stage_ids"]
	assert "plant/plant-0" in ids2 and "plant/plant-1" not in ids2, "no debe correr todo el frente de golpe"
	assert o2.progress["current"] == 2 and o2.progress["total"] == 4
	# Sub-progreso del fan-out (Fase 3) → la lista muestra "· sesión k/N".
	assert o2.progress["stage_label"] == "sesión"
	assert o2.progress["stage_current"] == 1 and o2.progress["stage_total"] == 3
	assert not o2.completed

	o3 = d.step(payload, o2.new_checkpoint)
	ids3 = o3.new_checkpoint["completed_stage_ids"]
	assert "plant/plant-1" in ids3 and "plant/plant-2" not in ids3
	assert o3.progress["current"] == 3

	o4 = d.step(payload, o3.new_checkpoint)
	assert o4.completed and o4.progress["current"] == 4 and o4.progress["percent"] == 100
	assert "plant/plant-2" in o4.new_checkpoint["completed_stage_ids"]
	assert "plant" in o4.new_checkpoint["completed_stage_ids"]  # compuesto propagado done


def test_sin_stepwise_todo_el_frente_en_un_step(tmp_path, monkeypatch):
	"""Contraste: sin el flag, las 3 instancias corren en el MISMO step (contador
	congelado mientras corre) — la razón de ser de `fanout_stepwise`."""
	_fake_factory(monkeypatch)
	(Path(tmp_path) / ".cell" / "reports").mkdir(parents=True)
	d = DagJobDriver()
	payload = _payload(str(tmp_path), stepwise=False)

	o1 = d.step(payload, {})
	o2 = d.step(payload, o1.new_checkpoint)
	assert o2.completed
	for i in range(3):
		assert f"plant/plant-{i}" in o2.new_checkpoint["completed_stage_ids"]
