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
		d.validate(
			_payload(
				"/tmp",
				[
					{"id": "a", "type": "agent", "minion": "agent", "model": "m", "prompt": "x"},
					{"id": "a", "type": "command", "minion": "command_runner"},
				],
			)
		)


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
	payload = _payload(
		str(ws),
		[
			{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "do X"},
			{"id": "smoke", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "smoke it", "depends_on": ["impl"]},
		],
	)
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	assert not o1.completed
	o2 = d.step(payload, o1.new_checkpoint)
	assert o2.completed
	assert o2.new_checkpoint["completed_stage_ids"] == ["impl", "smoke"]
	# Etapa agéntica: el envelope del minion va aparte; `impl.json` queda para el
	# reporte de rol que escribe el propio agente (contrato zero-trust de forge).
	assert (ws / ".cell" / "reports" / "impl.envelope.json").is_file()
	assert not (ws / ".cell" / "reports" / "impl.json").exists()


# ── Ejecución: comandos (no-agénticos) ────────────────────────────────────────
def test_dag_command_stage(tmp_path, monkeypatch):
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(
		str(ws),
		[
			{"id": "gen", "type": "command", "minion": "command_runner", "command": "echo hi > gen.txt"},
		],
	)
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
	payload = _payload(
		str(ws),
		[
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
		],
	)
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	o2 = d.step(payload, o1.new_checkpoint)
	# las dos lentes del panel en el mismo step, luego el compuesto se marca done
	assert o2.completed
	ids = o2.new_checkpoint["completed_stage_ids"]
	assert "panel/lens-a" in ids and "panel/lens-b" in ids and "panel" in ids


# ── Pausa a mitad de step: flag `pausable` + gate de grupo paralelo ──────────

def test_group_pause_gate_rule():
	"""La pausa a mitad de un grupo paralelo solo se honra cuando TODAS las etapas
	aún en vuelo son pausables; se reevalúa en cada completación."""
	from red_pill.jobs.drivers.dag import _GroupPauseGate

	gate = _GroupPauseGate(
		[
			("a", {"pausable": True}),
			("b", {"pausable": False}),  # delicada: su trabajo no debe descartarse
		]
	)
	gate.request_pause()
	# B (no-pausable) sigue en vuelo → NO se puede pausar.
	assert gate.pause_requested()
	assert gate.can_pause() is False
	# B completa → los restantes en vuelo (A, pausable) permiten pausar.
	gate.finished("b")
	assert gate.can_pause() is True
	gate.finished("a")
	assert gate.can_pause() is True  # grupo vacío → condición vacua


def test_dag_pausable_gates_probe_injection(tmp_path, monkeypatch):
	"""Una etapa no-pausable NO recibe sonda; una pausable sí (con job atado)."""
	from red_pill.jobs.drivers.dag import DagJobDriver

	d = DagJobDriver()
	d.bind("job-deadbeef")
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(
		str(ws),
		[
			{"id": "soft", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "p"},
			{"id": "delicate", "type": "agent", "minion": "agent", "pausable": False, "model": "opencode-go/deepseek-v4-pro", "prompt": "d"},
		],
	)
	d.step(payload, {})
	by_task = {task: kwargs for task, kwargs in calls}
	assert by_task["p"]["pause_probe"] is not None  # pausable por defecto → sonda
	assert by_task["d"]["pause_probe"] is None  # pausable:false → sin sonda


def test_dag_sequential_pause_honored_checkpoint_preserved(tmp_path, monkeypatch):
	"""Una etapa secuencial pausable cuya sonda dispara honra la pausa y preserva
	en el checkpoint las etapas ya completadas de este step."""
	from red_pill.jobs.drivers.dag import DagJobDriver

	class _ProbeAgent:
		async def execute(self, task, **kwargs):
			probe = kwargs.get("pause_probe")
			if probe is not None:
				probe()  # el operador pausó → lanza JobPauseRequested
			return {"status": "success", "summary": "hecho"}

	def _create(minion_id, **kw):
		if minion_id == "command_runner":
			class _Cmd:
				async def execute(self, task, **kwargs):
					return {"status": "success", "returncode": 0, "stdout": "ok", "summary": "ok"}
			return _Cmd()
		if minion_id == "agent":
			return _ProbeAgent()
		raise KeyError(minion_id)

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(_create))
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent" if mid == "agent" else "command")
	monkeypatch.setattr(
		"red_pill.cognitive.queue_manager.CognitiveQueueManager.get_task",
		lambda self, tid: {"id": tid, "status": "PAUSING"},
	)

	d = DagJobDriver()
	d.bind("job-deadbeef")
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	payload = _payload(
		str(ws),
		[
			{"id": "gen", "type": "command", "minion": "command_runner", "command": "echo ok > gen.txt"},
			{"id": "soft", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "p"},
		],
	)
	o = d.step(payload, {})
	assert o.pause_requested is True
	assert not o.completed
	# La etapa de comando ya completada se preserva; la pausable en vuelo no.
	assert "gen" in o.new_checkpoint["completed_stage_ids"]
	assert "soft" not in o.new_checkpoint["completed_stage_ids"]


def test_dag_parallel_level_gate(tmp_path, monkeypatch):
	"""parallel declarado en nivel > max_parallel_level → secuencial (sin error)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(
		str(ws),
		[
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
		],
		max_parallel_level=1,
	)
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
	payload = _payload(
		str(ws),
		[
			{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x", "on_fail": "stop"},
		],
	)
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
	payload = _payload(
		str(ws),
		[
			{"id": "impl", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x", "on_fail": "warn"},
		],
	)
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
	payload = _payload(
		str(ws),
		[
			{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "a"},
			{"id": "b", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "b", "depends_on": ["a"]},
		],
	)
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
	payload = _payload(
		str(ws),
		[
			{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "a"},
		],
	)
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
	payload = _payload(
		str(ws),
		[
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
					{
						"id": "lens-perf-repro",
						"type": "agent",
						"minion": "agent",
						"model": "opencode-go/deepseek-v4-flash",
						"prompt": "reproduce perf",
					},
					{
						"id": "judge",
						"type": "agent",
						"minion": "agent",
						"model": "opencode-go/kimi-k2.7-code",
						"depends_on": ["lens-correctness", "lens-env-segregation", "lens-plan", "lens-security", "lens-perf-repro"],
						"prompt": "lee .cell/reports/panel/lens-*.json y adjudica",
					},
				],
			},
		],
	)
	o1 = d.step(payload, {})
	assert o1.new_checkpoint["completed_stage_ids"] == ["impl"]
	o2 = d.step(payload, o1.new_checkpoint)
	# Las 5 lentes corren en UN step (threads, paralelas); el judge con depends_on
	# es una oleada posterior (espera sus reportes) → el compuesto 'panel' se marca
	# done en el step siguiente. Checkpoint por sub-etapa (RFC §4.1).
	assert o2.new_checkpoint["completed_stage_ids"] == ["impl"] + [
		f"panel/lens-{lid}" for lid in ("correctness", "env-segregation", "plan", "security", "perf-repro")
	]
	# §3: StepOutcome informa el paralelismo real del step (RFC_JOB_DAG §3)
	assert o2.concurrency is not None
	assert o2.concurrency["parallel_groups"] == 1
	assert o2.concurrency["parallel_stages"] == 5
	assert o2.concurrency["actually_parallel"] is True
	o3 = d.step(payload, o2.new_checkpoint)
	assert o3.completed
	ids = o3.new_checkpoint["completed_stage_ids"]
	for lid in ("lens-correctness", "lens-env-segregation", "lens-plan", "lens-security", "lens-perf-repro", "judge"):
		assert f"panel/{lid}" in ids, f"falta panel/{lid}"
	assert "panel" in ids
	# Cada sub-etapa serializó su envelope en .cell/reports/panel/. La ruta
	# `<lente>.json` NO se toca: es donde la lente escribe su refutación conforme
	# a schema, y es lo que el judge lee (si el DAG la pisara, el judge adjudicaría
	# sobre envelopes en vez de sobre evidencia).
	for lid in ("lens-correctness", "lens-env-segregation", "lens-plan", "lens-security", "lens-perf-repro", "judge"):
		assert (ws / ".cell" / "reports" / "panel" / f"{lid}.envelope.json").is_file(), f"falta envelope panel/{lid}"
		assert not (ws / ".cell" / "reports" / "panel" / f"{lid}.json").exists(), f"el DAG pisó el reporte de rol panel/{lid}.json"


# ── Funciones de módulo: _gpu_health_probe y _resolve_minion_kind ────────────


def test_gpu_health_probe_sin_binario(monkeypatch):
	"""Sin nvidia-smi en PATH → (False, 0, 0)."""
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod.shutil, "which", lambda name: None)
	assert dag_mod._gpu_health_probe() == (False, 0, 0)


def test_gpu_health_probe_exit_nonzero(monkeypatch):
	"""nvidia-smi presente pero exit!=0 → (False, 0, 0)."""
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
	monkeypatch.setattr(dag_mod.subprocess, "run", lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": ""})())
	assert dag_mod._gpu_health_probe() == (False, 0, 0)


def test_gpu_health_probe_ok_con_ngl(monkeypatch):
	"""nvidia-smi OK (8192 MB) y llama-server con -ngl 33 → (True, 8192, 33)."""
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
	responses = iter(
		[
			type("R", (), {"returncode": 0, "stdout": "8192\n"})(),
			type("R", (), {"returncode": 0, "stdout": "llama-server ... -ngl 33\n"})(),
		]
	)
	monkeypatch.setattr(dag_mod.subprocess, "run", lambda *a, **kw: next(responses))
	usable, free_mb, ngl = dag_mod._gpu_health_probe()
	assert (usable, free_mb, ngl) == (True, 8192, 33)


def test_gpu_health_probe_ngl_malformado(monkeypatch):
	"""llama-server con -ngl no numérico → ngl=0 (CPU disfrazada detectada)."""
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
	responses = iter(
		[
			type("R", (), {"returncode": 0, "stdout": "4096\n"})(),
			type("R", (), {"returncode": 0, "stdout": "llama-server ... -ngl abc\n"})(),
		]
	)
	monkeypatch.setattr(dag_mod.subprocess, "run", lambda *a, **kw: next(responses))
	usable, _free_mb, ngl = dag_mod._gpu_health_probe()
	assert usable is True and ngl == 0


def test_gpu_health_probe_excepcion(monkeypatch):
	"""nvidia-smi lanza excepción → (False, 0, 0)."""
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
	monkeypatch.setattr(dag_mod.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
	assert dag_mod._gpu_health_probe() == (False, 0, 0)


def test_resolve_minion_kind_no_registrado(monkeypatch):
	"""Un minion_id desconocido → None (no registrado en MinionFactory)."""
	import red_pill.jobs.drivers.dag as dag_mod
	import red_pill.swarm.factory as fac

	monkeypatch.setattr(fac.MinionFactory, "create", staticmethod(lambda mid, **kw: None))
	assert dag_mod._resolve_minion_kind("no_existe") is None


def test_resolve_minion_kind_logic(monkeypatch):
	"""Un minion de lógica pura (echo_mirror) → 'logic' (no-agéntico)."""
	import red_pill.jobs.drivers.dag as dag_mod

	class _LogicMinion:
		pass

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "logic" if mid == "echo_mirror" else None)
	assert dag_mod._resolve_minion_kind("echo_mirror") == "logic"


# ── Regresiones 2026-08-14 (revisión post-bake-off) ──────────────────────────
def test_dag_gpu_deferral_propagates_with_on_fail_warn(tmp_path, monkeypatch):
	"""JobDeferred es espera de entorno, no fallo: con on_fail=warn la etapa GPU
	NO debe marcarse done — el deferral tiene que llegar al runner (R1)."""
	from red_pill.jobs.drivers.base import JobDeferred

	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)

	def _defer(stage, stage_path, payload):
		raise JobDeferred(f"GPU no disponible para etapa '{stage_path}'")

	monkeypatch.setattr(d, "_preflight_stage_gpu", lambda stage, stage_path, payload: _defer(stage, stage_path, payload))
	payload = _payload(
		str(ws),
		[
			{
				"id": "consolidation",
				"type": "agent",
				"minion": "agent",
				"model": "opencode-go/deepseek-v4-pro",
				"prompt": "x",
				"on_fail": "warn",
				"requires_gpu": True,
			},
		],
	)
	with pytest.raises(JobDeferred):
		d.step(payload, {})
	assert not calls  # el minion nunca llegó a ejecutarse


def test_dag_handoff_with_only_leaves_completes_composite_dep(tmp_path, monkeypatch):
	"""Un checkpoint de handoff que lista solo hojas debe satisfacer depends_on
	sobre el compuesto padre (antes: frente vacío + mismo checkpoint = livelock)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(
		str(ws),
		[
			{
				"id": "P",
				"type": "compound",
				"sub_etapas": [
					{"id": "x", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x"},
				],
			},
			{"id": "b", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "b", "depends_on": ["P"]},
		],
	)
	handoff = {"completed_stage_ids": ["P/x"], "results": {"P/x": "hecho-inline"}}
	o = d.step(payload, handoff)
	assert o.completed
	assert "b" in o.new_checkpoint["results"]


def test_dag_empty_front_incomplete_raises_instead_of_livelock(tmp_path, monkeypatch):
	"""Frente vacío sin terminar = error diagnóstico, jamás completed=False estéril."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(
		str(ws),
		[
			{"id": "b", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "b", "depends_on": ["ghost"]},
		],
	)
	with pytest.raises(RuntimeError, match="sin frente ejecutable"):
		d.step(payload, {})


# ── Motor: cotas que atan y on_fail heredado (2026-08-14) ────────────────────
def test_dag_stage_timeout_capped_by_step_budget(tmp_path, monkeypatch):
	"""El timeout de la etapa se acota por lo que queda de la cota del step:
	sin esto `control.max_step_minutes` era decorativo."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	seen = {}

	class _Spy:
		async def execute(self, task, **kwargs):
			seen["timeout"] = kwargs.get("timeout")
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(lambda mid, **kw: _Spy()))
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent")
	payload = _payload(
		str(ws),
		[{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x", "timeout": 6000}],
	)
	d.bind("job-1", attempts=0, step_timeout_s=30)  # cota del runner
	d.step(payload, {})
	assert seen["timeout"] <= 30, f"la etapa ignoró el presupuesto del step: {seen['timeout']}"


def test_dag_yields_at_budget_boundary_keeping_progress(tmp_path, monkeypatch):
	"""Cota agotada en frontera: CEDE con lo hecho (checkpoint persistido) en vez
	de abatir el step — abatirlo re-ejecutaría etapas con efectos ya aplicados."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)
	payload = _payload(
		str(ws),
		[
			{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "a"},
			{"id": "b", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "b"},
			{"id": "c", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "c"},
		],
	)
	d.bind("job-1", attempts=0, step_timeout_s=30)
	import red_pill.jobs.drivers.dag as dag_mod

	# Cada etapa consume 60s de reloj: la cota de 30s se agota tras la primera.
	state = {"t": 1000.0}
	monkeypatch.setattr(dag_mod.time, "monotonic", lambda: state["t"])
	real_run_atomic = d._run_atomic

	def _slow(payload_, stage_, path_, gate_=None):
		state["t"] += 60
		return real_run_atomic(payload_, stage_, path_, gate_)

	monkeypatch.setattr(d, "_run_atomic", _slow)
	o = d.step(payload, {})
	assert not o.completed
	assert o.new_checkpoint["completed_stage_ids"] == ["a"], "cedió sin conservar lo hecho"
	assert len(calls) == 1, "arrancó una etapa con la cota ya agotada"


def test_dag_on_fail_inherited_from_compound(tmp_path, monkeypatch):
	"""`on_fail: stop` en una etapa COMPUESTA acota a sus hojas (antes: letra muerta)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)

	class _Failing:
		async def execute(self, task, **kwargs):
			return {"status": "failed", "error": "boom"}

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(lambda mid, **kw: _Failing()))
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent")
	payload = _payload(
		str(ws),
		[
			{
				"id": "fase",
				"type": "compound",
				"on_fail": "stop",  # la hoja no lo declara: lo hereda
				"sub_etapas": [{"id": "x", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x"}],
			}
		],
	)
	with pytest.raises(RuntimeError, match="on_fail=stop"):
		d.step(payload, {})


def test_dag_validate_rejects_bad_on_fail(tmp_path):
	"""Una errata en on_fail se rechaza en el submit (antes: 'warn' silencioso)."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	payload = _payload(
		str(ws),
		[{"id": "a", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x", "on_fail": "warm"}],
	)
	with pytest.raises(ValueError, match="on_fail"):
		d.validate(payload)


# ── FASE 2: type: dag (composición por REFERENCIA, RFC_JOB_DAG §4.5) ──────────

def _recipe(reference: str, stages):
	"""Simula load_recipe: devuelve la 5-tupla (source, payload, priority, parent, is_seed)."""
	return "dag_job", {"manifest": {"workdir": ".", "stages": stages}}, 5, None, False


def test_dag_type_dag_expands_and_runs(tmp_path, monkeypatch):
	"""Una etapa type: dag referencia una receta de 2 etapas → se expande a compound
	y ambas hojas corren con ids aplanados bajo el id de la etapa referenciante."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)
	calls = []
	_patch_minion_factory(monkeypatch, calls)

	# Receta simulada: 2 etapas command.
	monkeypatch.setattr(
		DagJobDriver,
		"_load_recipe",
		classmethod(lambda cls, ref: _recipe(ref, [
			{"id": "r1", "type": "command", "minion": "command_runner", "command": "echo uno"},
			{"id": "r2", "type": "command", "minion": "command_runner", "command": "echo dos", "depends_on": ["r1"]},
		])),
	)
	payload = _payload(str(ws), [
		{"id": "sub", "type": "dag", "recipe": "test-recipe"},
	])
	# El submit expande SIEMPRE: el runner nunca ve type: dag.
	expanded = DagJobDriver.expand_manifest(payload)
	d.validate(expanded)
	# r2 depende de r1: el frente de un step ejecuta solo las hojas con deps
	# satisfechas (como el judge del panel) — dos steps.
	o1 = d.step(expanded, {})
	assert not o1.completed
	assert "sub/r1" in o1.new_checkpoint["completed_stage_ids"]
	o2 = d.step(expanded, o1.new_checkpoint)
	assert o2.completed
	ids = o2.new_checkpoint["completed_stage_ids"]
	assert "sub/r1" in ids and "sub/r2" in ids and "sub" in ids
	# Los reportes de las hojas aplanadas se serializan por ruta.
	assert (ws / ".cell" / "reports" / "sub" / "r1.json").is_file()
	assert (ws / ".cell" / "reports" / "sub" / "r2.json").is_file()


def test_dag_type_dag_unknown_recipe_rejected(tmp_path, monkeypatch):
	"""Receta inexistente → ValueError en validate()."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()

	def _missing(ref):
		raise FileNotFoundError(f"no hay ninguna receta '{ref}'")

	monkeypatch.setattr(DagJobDriver, "_load_recipe", classmethod(lambda cls, ref: _missing(ref)))
	payload = _payload(str(ws), [{"id": "sub", "type": "dag", "recipe": "no-existe"}])
	with pytest.raises((ValueError, FileNotFoundError)):
		d.validate(payload)


def test_dag_type_dag_cycle_rejected(tmp_path, monkeypatch):
	"""Ciclo (receta A referencia a A) → ValueError en validate()."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()

	def _cyclic(ref):
		return _recipe(ref, [{"id": "inner", "type": "dag", "recipe": ref}])

	monkeypatch.setattr(DagJobDriver, "_load_recipe", classmethod(lambda cls, ref: _cyclic(ref)))
	payload = _payload(str(ws), [{"id": "sub", "type": "dag", "recipe": "A"}])
	with pytest.raises(ValueError, match="cíclica"):
		d.validate(payload)
	with pytest.raises(ValueError, match="cíclica"):
		DagJobDriver.expand_manifest(payload)


def test_dag_type_dag_failsafe_models_propagate(tmp_path, monkeypatch):
	"""El fail-safe de modelos se propaga: receta con etapa agéntica en flash → ValueError."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	ws.mkdir()
	monkeypatch.setattr(
		DagJobDriver,
		"_load_recipe",
		classmethod(lambda cls, ref: _recipe(ref, [
			{"id": "agent-inner", "type": "agent", "minion": "agent", "model": "flash", "prompt": "x"},
		])),
	)
	payload = _payload(str(ws), [{"id": "sub", "type": "dag", "recipe": "bad-recipe"}])
	with pytest.raises(ValueError, match="sin modelo configurado"):
		d.validate(payload)


def test_dag_type_dag_on_fail_inherited(tmp_path, monkeypatch):
	"""on_fail: stop en la etapa type: dag lo heredan las hojas de la receta expandida."""
	d = DagJobDriver()
	ws = tmp_path / "ws"
	(ws / ".cell" / "reports").mkdir(parents=True)

	class _Failing:
		async def execute(self, task, **kwargs):
			return {"status": "failed", "error": "boom"}

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(lambda mid, **kw: _Failing()))
	import red_pill.jobs.drivers.dag as dag_mod

	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent")
	monkeypatch.setattr(
		DagJobDriver,
		"_load_recipe",
		classmethod(lambda cls, ref: _recipe(ref, [
			{"id": "inner", "type": "agent", "minion": "agent", "model": "opencode-go/deepseek-v4-pro", "prompt": "x"},
		])),
	)
	payload = _payload(str(ws), [{"id": "sub", "type": "dag", "recipe": "fragile", "on_fail": "stop"}])
	expanded = DagJobDriver.expand_manifest(payload)
	d.validate(expanded)
	with pytest.raises(RuntimeError, match="on_fail=stop"):
		d.step(expanded, {})


# ── Homónimos entre ramas: resolución por RUTA (auditoría 2026-08-21) ────────

def _homonym_stages():
	"""F1: scout→implementor(on_fail stop); F2: implementor(on_fail warn)→qa.
	Roles repetidos ENTRE fases: exactamente lo que emite manifest-compile.mjs."""
	return [
		{"id": "F1", "type": "compound", "sub_etapas": [
			{"id": "scout", "type": "agent", "minion": "agent", "model": "m", "prompt": "p"},
			{"id": "implementor", "type": "agent", "minion": "agent", "model": "m", "prompt": "p", "depends_on": ["scout"], "on_fail": "stop"},
		]},
		{"id": "F2", "type": "compound", "depends_on": ["F1"], "sub_etapas": [
			{"id": "implementor", "type": "agent", "minion": "agent", "model": "m", "prompt": "boom", "on_fail": "warn"},
			{"id": "qa", "type": "agent", "minion": "agent", "model": "m", "prompt": "p", "depends_on": ["implementor"]},
		]},
	]


def test_resolve_on_fail_by_path_not_by_homonym():
	from red_pill.jobs.drivers.dag import _resolve_on_fail

	stages = _homonym_stages()
	assert _resolve_on_fail(stages, "F2/implementor") == "warn"  # antes: stop (homónimo F1)
	assert _resolve_on_fail(stages, "F1/implementor") == "stop"


def test_homonym_leaf_failure_honors_own_on_fail(tmp_path, monkeypatch):
	"""La hoja F2/implementor (warn) falla → el job NO aborta pese al homónimo stop de F1."""
	import red_pill.jobs.drivers.dag as dag_mod

	record = []

	class _Fake:
		async def execute(self, task, **kwargs):
			record.append(task)
			if task == "boom":
				return {"status": "failed", "error": "kaput"}
			return {"status": "success", "summary": "ok"}

	monkeypatch.setattr("red_pill.swarm.factory.MinionFactory.create", staticmethod(lambda mid, **kw: _Fake()))
	monkeypatch.setattr(dag_mod, "_resolve_minion_kind", lambda mid: "agent")

	drv = DagJobDriver()
	drv.bind("job-homonym")
	payload = _payload(str(tmp_path), _homonym_stages())
	checkpoint = {}
	outcome = None
	for _ in range(10):
		outcome = drv.step(payload, checkpoint)
		checkpoint = outcome.new_checkpoint
		if outcome.completed:
			break
	assert outcome is not None and outcome.completed  # warn honrado: la misión completa
	assert "FAILED" in checkpoint["results"]["F2/implementor"]


def test_run_atomic_passes_job_id(tmp_path, monkeypatch):
	"""Los minions reciben el job_id que los ejecuta (idempotencia del gate)."""
	record = []
	_patch_minion_factory(monkeypatch, record)
	drv = DagJobDriver()
	drv.bind("job-abc-123")
	stages = [{"id": "a", "type": "agent", "minion": "agent", "model": "m", "prompt": "x"}]
	drv.step(_payload(str(tmp_path), stages), {})
	assert record[0][1].get("job_id") == "job-abc-123"
