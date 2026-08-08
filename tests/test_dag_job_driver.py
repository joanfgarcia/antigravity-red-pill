"""DagJobDriver (RFC_JOB_DAG_PARALLELIZATION v0.7): árbol recursivo de etapas,
validación cruzada type↔minion, fail-safe de modelos, fan-out paralelo, control
transferible."""

import json

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.jobs.drivers.dag import DagJobDriver


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


@pytest.fixture(autouse=True)
def silent_reports(monkeypatch):
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda *a, **kw: None)


def _payload(workdir: str, stages, mission_id="m1", **extra):
	base = {"mission_id": mission_id, "manifest": {"workdir": workdir, "stages": stages}}
	base.update(extra)
	return base


# Un minion agéntico de prueba que ejecuta sin bridge real (usa EchoMinion, lógica
# pura). Para etapas `agent` de prueba usamos un monkeypatch de MinionFactory.
def _patch_minion_factory(monkeypatch, record):
	"""Sustituye MinionFactory.create por un minion de prueba que registra llamadas."""

	class _FakeAgent:
		async def execute(self, task, **kwargs):
			record.append((task, kwargs))
			return {"status": "success", "response": "hecho", "summary": "hecho"}

	class _FakeCommand:
		async def execute(self, task, **kwargs):
			record.append((task, kwargs))
			return {"status": "success", "returncode": 0, "stdout": "ok", "summary": "ok"}

	def _create(minion_id, **kw):
		if minion_id == "agent":
			return _FakeAgent()
		if minion_id == "command_runner":
			return _FakeCommand()
		raise KeyError(minion_id)

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(_create))
	# el resolve del módulo importa la factory real: hay que parchear también el
	# _resolve_minion_kind para que conozca agent/command sin el isinstance real
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent" if mid == "agent" else "command")


# ── Validación ────────────────────────────────────────────────────────────────
def test_dag_validate_requires_mission():
	d = DagJobDriver()
	with pytest.raises(ValueError, match="mission_id"):
		d.validate({"manifest": {"workdir": "/tmp", "stages": [{"id": "a", "type": "agent", "minion": "agent", "model": "m", "prompt": "x"}]}})


def test_dag_validate_rejects_bad_type():
	d = DagJobDriver()
	with pytest.raises(ValueError, match="type"):
		d.validate(_payload("/tmp", [{"id": "a", "type": "bogus", "minion": "agent", "model": "m", "prompt": "x"}]))


def test_dag_validate_duplicate_path():
	d = DagJobDriver()
	with pytest.raises(ValueError, match="duplicate"):
		d.validate(_payload("/tmp", [
			{"id": "a", "type": "agent", "minion": "agent", "model": "m", "prompt": "x"},
			{"id": "a", "type": "command", "minion": "command_runner"},
		]))


def test_dag_validate_rejects_flash_model(tmp_path):
	"""Fail-safe de modelos (fleco 3): etapa agéntica sin modelo real → bloqueada."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	with pytest.raises(ValueError, match="sin modelo configurado"):
		d.validate(_payload(str(ws), [{"id": "a", "type": "agent", "minion": "agent", "model": "flash", "prompt": "x"}]))


def test_dag_validate_rejects_missing_prompt(tmp_path):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	with pytest.raises(ValueError, match="prompt"):
		d.validate(_payload(str(ws), [{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/x", "prompt": ""}]))


def test_dag_validate_compound_without_minion(tmp_path):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	with pytest.raises(ValueError, match="minion"):
		d.validate(_payload(str(ws), [{"id": "c", "type": "compound", "minion": "agent", "sub_etapas": []}]))


# ── Ejecución: árbol secuencial ───────────────────────────────────────────────
def test_dag_linear_agentic_runs_in_order(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "do X"},
		{"id": "smoke", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "smoke it", "depends_on": ["impl"]},
	])
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	assert not o1.completed
	o2 = d.step(payload, o1.new_checkpoint)
	assert o2.completed
	assert o2.new_checkpoint["completed_stage_ids"] == ["impl", "smoke"]
	assert (ws / ".cell" / "reports" / "impl.json").is_file()


# ── Ejecución: comandos (no-agénticos) ────────────────────────────────────────
def test_dag_command_stage(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(str(ws), [
		{"id": "gen", "type": "command", "minion": "command_runner", "command": "echo hi > gen.txt"},
	])
	o = d.step(payload, {})
	assert o.completed
	assert o.new_checkpoint["results"]["gen"] == "ok"


# ── Ejecución: compuesto con fan-out paralelo ─────────────────────────────────
def test_dag_compound_parallel_runs_all(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "do X"},
		{
			"id": "panel",
			"type": "compound",
			"parallel": True,
			"on_fail": "warn",
			"depends_on": ["impl"],
			"sub_etapas": [
				{"id": "lens-a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "lens a"},
				{"id": "lens-b", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "lens b"},
			],
		},
	])
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	o2 = d.step(payload, o1.new_checkpoint)
	# las dos lentes del panel en el mismo step, luego el compuesto se marca done
	assert o2.completed
	ids = o2.new_checkpoint["completed_stage_ids"]
	assert "panel/lens-a" in ids and "panel/lens-b" in ids and "panel" in ids


def test_dag_parallel_level_gate(tmp_path, monkeypatch):
	"""parallel declarado en nivel > max_parallel_level → secuencial (sin error)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(str(ws), [
		{
			"id": "deep",
			"type": "compound",
			"sub_etapas": [
				{
					"id": "inner",
					"type": "compound",
					"parallel": True,
					"sub_etapas": [
						{"id": "x", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x"},
						{"id": "y", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "y"},
					],
				},
			],
		},
	], max_parallel_level=1)
	# nivel del nodo 'inner' = 2 > 1 → sus sub-etapas se ejecutan secuenciales
	while True:
		o = d.step(payload, {})
		if o.completed:
			break
	assert o.completed
	assert {"deep/inner/x", "deep/inner/y"} <= set(o.new_checkpoint["completed_stage_ids"])


# ── Fallos: on_fail stop/warn ─────────────────────────────────────────────────
def test_dag_on_fail_stop_raises(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)

	class _Failing:
		async def execute(self, task, **kwargs):
			return {"status": "failed", "error": "boom"}

	def _create(minion_id, **kw):
		return _Failing()

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(_create))
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent")
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x", "on_fail": "stop"},
	])
	with pytest.raises(RuntimeError, match="on_fail=stop"):
		d.step(payload, {})


def test_dag_on_fail_warn_continues(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)

	class _Failing:
		async def execute(self, task, **kwargs):
			return {"status": "failed", "error": "boom"}

	def _create(minion_id, **kw):
		return _Failing()

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(_create))
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent")
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x", "on_fail": "warn"},
	])
	o = d.step(payload, {})
	assert o.completed
	assert "FAILED" in o.new_checkpoint["results"]["impl"]


# ── Control transferible ──────────────────────────────────────────────────────
def test_dag_transferable_control(tmp_path, monkeypatch):
	"""Un checkpoint escrito desde fuera (handoff) se respeta."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(str(ws), [
		{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "a"},
		{"id": "b", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "b", "depends_on": ["a"]},
	])
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
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(str(ws), [
		{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "a"},
	])
	d.step(payload, {})
	status = json.loads((ws / ".cell" / "dag_status.json").read_text())
	assert status["completed"] == 1 and status["total"] == 1
	assert status["status"] == "completed"


def test_dag_forge_panel_L3(tmp_path, monkeypatch):
	"""Paso 5 del RFC: el panel adversarial de forge como etapa compuesta parallel.
	Las 5 lentes corren en el mismo step (threads) y el judge espera sus reportes
	vía depends_on; cada sub-etapa serializa su dict en .cell/reports/panel/."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(str(ws), [
		{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "implementa"},
		{
			"id": "panel",
			"type": "compound",
			"parallel": True,
			"on_fail": "warn",
			"depends_on": ["impl"],
			"sub_etapas": [
				{"id": "lens-correctness", "type": "agent", "minion": "agent", "model": "opencode/big-pickle", "prompt": "refuta correctness"},
				{"id": "lens-env-segregation", "type": "agent", "minion": "agent", "model": "opencode-go/mimo-v2.5-pro", "prompt": "refuta env"},
				{"id": "lens-plan", "type": "agent", "minion": "agent", "model": "opencode-go/mimo-v2.5-pro", "prompt": "refuta plan"},
				{"id": "lens-security", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "refuta security"},
				{"id": "lens-perf-repro", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-flash", "prompt": "reproduce perf"},
				{"id": "judge", "type": "agent", "minion": "agent", "model": "opencode-go/kimi-k2.7-code",
					"depends_on": ["lens-correctness", "lens-env-segregation", "lens-plan", "lens-security", "lens-perf-repro"],
					"prompt": "lee .cell/reports/panel/lens-*.json y adjudica"},
			],
		},
	])
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	o2 = d.step(payload, o1.new_checkpoint)
	# Las 5 lentes corren en UN step (threads, paralelas); el judge con depends_on
	# es una oleada posterior (espera sus reportes) → el compuesto 'panel' se marca
	# done en el step siguiente. Checkpoint por sub-etapa (RFC §4.1).
	assert o2.new_checkpoint["completed_stage_ids"] == ["impl"] + [f"panel/lens-{lid}" for lid in ("correctness", "env-segregation", "plan", "security", "perf-repro")]
	o3 = d.step(payload, o2.new_checkpoint)
	assert o3.completed
	ids = o3.new_checkpoint["completed_stage_ids"]
	for lid in ("lens-correctness", "lens-env-segregation", "lens-plan", "lens-security", "lens-perf-repro", "judge"):
		assert f"panel/{lid}" in ids, f"falta panel/{lid}"
	assert "panel" in ids
	# Cada sub-etapa serializó su reporte en .cell/reports/panel/
	for lid in ("lens-correctness", "lens-env-segregation", "lens-plan", "lens-security", "lens-perf-repro", "judge"):
		assert (ws / ".cell" / "reports" / "panel" / f"{lid}.json").is_file(), f"falta reporte panel/{lid}.json"
