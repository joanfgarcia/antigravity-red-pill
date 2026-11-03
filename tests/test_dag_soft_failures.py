"""on_fail=warn (fail-soft) NO puede ser fail-silent (2026-11-03).

El DAG nocturno `e7b68d36` perdió 1 de 126 ítems de fan-out
(`memento-distill-83`, target con espacios) y nadie se enteró: `error_log`
del job en `null`, la etapa en `done`, y el único rastro era el string de
`results` en el checkpoint. La etapa degradada se sigue ejecutando tal como
diseñó fail-soft, pero la deuda tiene que estar escrita, agregada y en el
summary final — no disuelta en un `done` limpio.
"""

import pytest

from red_pill.jobs.drivers.dag import DagJobDriver


@pytest.fixture(autouse=True)
def silent_reports(monkeypatch):
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda *a, **kw: None)


def _payload(workdir: str, stages, mission_id="m1", **extra):
	base = {"mission_id": mission_id, "manifest": {"workdir": workdir, "stages": stages}}
	base.update(extra)
	return base


def _patch(monkeypatch, record, broken: set[str]):
	"""Minion de prueba: falla (status=failed) si la etapa está en `broken`."""

	class _Fake:
		async def execute(self, task, **kwargs):
			record.append(task)
			if task in broken or any(b in task for b in broken):
				return {"status": "failed", "error": f"boom:{task}"}
			return {"status": "success", "response": "hecho", "summary": "hecho"}

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(lambda mid, **kw: _Fake()))
	monkeypatch.setattr("red_pill.jobs.drivers.dag_types.base._resolve_minion_kind", lambda mid: "agent")


def _stage(sid: str, **extra):
	base = {"id": sid, "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": sid}
	base.update(extra)
	return base


def test_soft_failure_persisted_in_checkpoint(tmp_path, monkeypatch):
	"""Una etapa degradada con on_fail=warn deja rastro explícito en el checkpoint."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch(monkeypatch, [], {"roto"})

	out = d.step(_payload(str(ws), [_stage("roto", on_fail="warn")]), {})

	assert out.completed
	# sigue siendo fail-soft: la etapa cuenta como hecha y el job continúa
	assert out.new_checkpoint["stage_flags"]["roto"] == "done"
	assert "FAILED" in out.new_checkpoint["results"]["roto"]
	# ...pero el fallo ya no vive solo en ese string
	assert "soft_failures" in out.new_checkpoint
	assert "boom" in out.new_checkpoint["soft_failures"]["roto"]
	# el summary del step lo dice en voz alta
	assert "degradada" in out.summary


def test_soft_failure_survives_into_final_summary(tmp_path, monkeypatch):
	"""La deuda de un step intermedio llega al summary final del job."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch(monkeypatch, [], {"a"})

	payload = _payload(
		str(ws),
		[_stage("a", on_fail="warn"), _stage("b", depends_on=["a"])],
	)
	first = d.step(payload, {})
	assert not first.completed
	assert set(first.new_checkpoint["soft_failures"]) == {"a"}

	final = d.step(payload, first.new_checkpoint)
	assert final.completed
	assert set(final.new_checkpoint["soft_failures"]) == {"a"}
	assert "degradada" in final.summary
	assert "a" in final.summary


def test_clean_steps_do_not_grow_checkpoint(tmp_path, monkeypatch):
	"""Sin fallos no aparece la clave: un checkpoint limpio no engorda."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch(monkeypatch, [], set())

	out = d.step(_payload(str(ws), [_stage("ok")]), {})

	assert out.completed
	assert "soft_failures" not in out.new_checkpoint
	assert "degradada" not in out.summary


def test_on_fail_stop_still_aborts_without_soft_record(tmp_path, monkeypatch):
	"""El disyuntor no se confunde con deuda blanda: on_fail=stop corta igual."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	_patch(monkeypatch, [], {"roto"})

	with pytest.raises(RuntimeError, match="on_fail=stop"):
		d.step(_payload(str(ws), [_stage("roto", on_fail="stop")]), {})
