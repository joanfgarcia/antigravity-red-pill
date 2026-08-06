"""ScriptJobDriver — driver paramétrico genérico (RFC 2026-07-27).

Cubre las decisiones cerradas con el operador: progreso en tres modos con
`completion` universal (D6), timeout adaptativo como detector de cuelgue con
rastro forense y escalada (D5/D10), kill = PAUSED con marca de kill sucio (D1),
logs por job (D7), validación en el submit y tokenización sin shell (D8),
encadenado DAG en el mismo hilo (§4b) y teardown en todas las salidas (§7).
"""

import json
import os
import sys
from typing import Any, Dict

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_worker import process_driver_jobs
from red_pill.jobs.drivers import _REGISTRY, JobStepTimeout, ResumableJobDriver, StepOutcome, compute_step_timeout, register_driver, update_step_ema
from red_pill.jobs.drivers.script import ScriptJobDriver


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


@pytest.fixture
def clean_registry():
	saved = dict(_REGISTRY)
	_REGISTRY.clear()
	yield _REGISTRY
	_REGISTRY.clear()
	_REGISTRY.update(saved)


@pytest.fixture(autouse=True)
def silent_reports(monkeypatch):
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda *a, **kw: None)
	monkeypatch.setattr("red_pill.core.queue_worker.report_pain", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
	"""Los logs por job van al tmp de la prueba, nunca al state real del host."""
	state = tmp_path / "state"
	state.mkdir(parents=True, exist_ok=True)
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: state)
	return state


@pytest.fixture(autouse=True)
def fast_checkpoint_poll(monkeypatch):
	"""Sondeo fino: las pruebas duran milisegundos, no horas."""
	monkeypatch.setattr(ScriptJobDriver, "checkpoint_poll_seconds", 0.05)


@pytest.fixture(autouse=True)
def no_systemd(monkeypatch):
	"""Por defecto las pruebas corren sin envoltorio systemd (portables en CI)."""
	monkeypatch.setattr(ScriptJobDriver, "_has_systemd", staticmethod(lambda: False))


def _script(tmp_path, body: str) -> str:
	"""Escribe un script Python auxiliar y devuelve el comando que lo ejecuta."""
	path = tmp_path / "step.py"
	path.write_text(body, encoding="utf-8")
	return f"{sys.executable} {path}"


def _bind(driver: ScriptJobDriver, timeout: int = 300) -> ScriptJobDriver:
	driver.bind("job-1234-5678", attempts=0, step_timeout_s=timeout)
	return driver


# ── Validación en el submit (D8) ───────────────────────────────────────────


@pytest.mark.parametrize(
	"payload, expected",
	[
		({}, "step_command"),
		({"step_command": "echo hi", "progress": {"mode": "epochs"}}, "progress.mode"),
		({"step_command": "echo hi", "progress": {"mode": "bounded", "current_key": "e"}}, "checkpoint_file"),
		({"step_command": "echo hi", "checkpoint_file": "s.json", "progress": {"mode": "bounded"}}, "current_key"),
		({"step_command": "echo hi", "checkpoint_file": "s.json", "progress": {"mode": "bounded", "current_key": "e"}}, "total"),
		({"step_command": "echo hi", "cwd": "/no/existe/jamas"}, "cwd"),
		({"step_command": "echo hi", "defer_exit_code": 0}, "defer_exit_code"),
		({"step_command": "echo hi", "defer_exit_code": "75"}, "defer_exit_code"),
		({"step_command": "echo hi", "defer_exit_code": 124}, "defer_exit_code"),
		({"step_command": "echo hi", "pause_exit_code": 137}, "pause_exit_code"),
		({"step_command": "echo hi", "defer_exit_code": 75, "pause_exit_code": 75}, "no pueden coincidir"),
	],
)
def test_validate_rejects_malformed_payload_at_submit(payload, expected):
	"""Un payload incoherente muere al encolar, no tres intentos y FRUSTRATED después."""
	with pytest.raises(ValueError, match=expected):
		ScriptJobDriver.validate(payload)


def test_clear_stale_scope_resets_failed_unit(monkeypatch):
	"""Un scope abatido por RuntimeMaxSec queda en estado `failed`: is-active no lo
	ve (rc≠0) y el `stop` se omite, pero systemd-run rechaza el nombre ("already
	loaded") — la madrugada del 29 jul esto quemó el disyuntor del chronicle con
	fallos falsos. `reset-failed` incondicional libera el nombre siempre."""
	import subprocess as _sp

	calls = []

	class _Failed:
		returncode = 3  # unit en failed: is-active rc≠0, la rama del stop no entra

	monkeypatch.setattr(_sp, "run", lambda argv, **kw: calls.append(argv) or _Failed())

	driver = _bind(ScriptJobDriver())
	driver._clear_stale_scope()

	assert any("reset-failed" in argv for argv in calls)
	assert not any("stop" in argv for argv in calls)  # inactivo: no había nada que parar


def test_defer_exit_code_defers_without_burning_attempts(queue, clean_registry, tmp_path):
	"""El satélite declara un código de salida que significa "ahora no puedo"
	(el sueño con la GPU comprometida sale con 75): deferral limpio R1 — ni
	falso COMPLETED ni intento quemado."""
	register_driver(ScriptJobDriver)
	cmd = _script(tmp_path, "import sys; sys.exit(75)")
	job_id = queue.enqueue_task(source="script_job", payload={"step_command": cmd, "defer_exit_code": 75, "cwd": str(tmp_path)})

	assert process_driver_jobs(queue) == 0
	task = queue.get_task(job_id)
	assert task["status"] == "PENDING" and task["attempts"] == 0


def test_pause_exit_code_pauses_for_operator_review(queue, clean_registry, tmp_path):
	"""El satélite declara un código que significa "esto exige juicio humano" (un
	examen suspendido K veces). El viejo `sys.exit(1)` bajo el runner quemaba un
	intento y el retry automático se saltaba la puerta del examen (la transición
	fantasma a etapa 8 del 29 jul 2026); esto lo convierte en PAUSED con el
	checkpoint intacto, cero intentos, reanudable tras la revisión."""
	register_driver(ScriptJobDriver)
	cmd = _script(tmp_path, "import sys; sys.exit(78)")
	job_id = queue.enqueue_task(source="script_job", payload={"step_command": cmd, "pause_exit_code": 78, "cwd": str(tmp_path)})

	assert process_driver_jobs(queue) == 0
	task = queue.get_task(job_id)
	assert task["status"] == "PAUSED" and task["attempts"] == 0
	assert queue.resume_task(job_id)  # el operador revisa y reanuda


def test_validate_accepts_the_real_bit_payload(tmp_path):
	ScriptJobDriver.validate(
		{
			"cwd": str(tmp_path),
			"step_command": "python train.py",
			"checkpoint_file": "state.json",
			"progress": {"mode": "bounded", "current_key": "current_epoch", "total": 168, "stage_current_key": "current_stage_idx", "stage_total": 8},
			"completion": {"key": "milestones_achieved", "contains": "7_years"},
		}
	)


# ── Modos de progreso y finalización (D6) ──────────────────────────────────


def test_single_mode_completes_on_exit_zero(tmp_path):
	driver = _bind(ScriptJobDriver())
	outcome = driver.step({"cwd": str(tmp_path), "step_command": _script(tmp_path, "print('done')")}, {})

	assert outcome.completed
	assert outcome.progress["mode"] == "single"
	assert outcome.progress.get("percent") is None  # Sin total no se inventa porcentaje


def test_single_mode_failure_surfaces_the_real_error_not_the_wrapper(tmp_path):
	driver = _bind(ScriptJobDriver())
	command = _script(tmp_path, "import sys; print('ERROR CONCRETO DEL SCRIPT'); sys.exit(3)")

	with pytest.raises(RuntimeError, match="ERROR CONCRETO DEL SCRIPT"):
		driver.step({"cwd": str(tmp_path), "step_command": command}, {})


def test_bounded_mode_tracks_current_over_total(tmp_path):
	state = tmp_path / "state.json"
	body = f"""
import json, pathlib
p = pathlib.Path({str(state)!r})
data = json.loads(p.read_text()) if p.exists() else {{"epoch": 0}}
data["epoch"] += 1
p.write_text(json.dumps(data))
"""
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, body),
		"checkpoint_file": "state.json",
		"progress": {"mode": "bounded", "current_key": "epoch", "total": 2},
	}
	driver = _bind(ScriptJobDriver())

	first = driver.step(payload, {})
	assert not first.completed
	assert (first.progress["current"], first.progress["total"], first.progress["percent"]) == (1, 2, 50)

	second = driver.step(payload, first.new_checkpoint)
	assert second.completed
	assert second.progress["percent"] == 100


def test_completion_key_wins_in_bounded_mode_as_early_exit(tmp_path):
	"""D6: hay trabajos que cierran por hito evaluado, no por contador.

	La escuela de Bit otorga el hito cuando Samantha aprueba, en la época que
	sea: sin esta regla, la fase terminaría antes de tiempo o nunca.
	"""
	state = tmp_path / "state.json"
	state.write_text(json.dumps({"current_epoch": 25, "milestones_achieved": ["6_years", "7_years"]}))
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "bounded", "current_key": "current_epoch", "total": 168},
		"completion": {"key": "milestones_achieved", "contains": "7_years"},
	}

	outcome = _bind(ScriptJobDriver()).step(payload, {})

	assert outcome.completed  # 25 de 168 épocas, pero el hito ya está concedido
	assert outcome.progress["percent"] == 14


def test_completion_not_reached_keeps_running_past_total(tmp_path):
	"""La otra cara: sin hito, el contador por sí solo no cierra la fase."""
	state = tmp_path / "state.json"
	state.write_text(json.dumps({"current_epoch": 200, "milestones_achieved": ["6_years"]}))
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "bounded", "current_key": "current_epoch", "total": 168},
		"completion": {"key": "milestones_achieved", "contains": "7_years"},
	}

	outcome = _bind(ScriptJobDriver()).step(payload, {})

	assert not outcome.completed
	assert outcome.progress["percent"] == 100  # Satura, no miente


def test_unbounded_mode_shows_counter_without_percent(tmp_path):
	state = tmp_path / "state.json"
	state.write_text(json.dumps({"global_step": 4200, "phase_done": False}))
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "global_step"},
		"completion": {"key": "phase_done"},
	}

	outcome = _bind(ScriptJobDriver()).step(payload, {})

	assert not outcome.completed
	assert outcome.progress["current"] == 4200
	assert "percent" not in outcome.progress


def test_two_dimensional_progress_and_dynamic_total(tmp_path):
	"""Progreso 2D leyendo claves que el estado YA tiene, sin tocar el script."""
	state = tmp_path / "state.json"
	state.write_text(json.dumps({"current_epoch": 23, "current_stage_idx": 6, "max_epochs": 168}))
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {
			"mode": "bounded",
			"current_key": "current_epoch",
			"total_key": "max_epochs",
			"stage_current_key": "current_stage_idx",
			"stage_total": 8,
			"stage_offset": 1,
			"stage_label": "fase",
		},
	}

	progress = _bind(ScriptJobDriver()).step(payload, {}).progress

	assert (progress["current"], progress["total"]) == (23, 168)
	assert (progress["stage_current"], progress["stage_total"], progress["stage_label"]) == (7, 8, "fase")


# ── Watchdog de no-progreso ────────────────────────────────────────────────


def test_no_progress_watchdog_breaks_the_sterile_loop(tmp_path, monkeypatch):
	"""Exit 0 sin avanzar no es fallo, ni cuelgue, ni deferral: sin guard, bucle infinito."""
	monkeypatch.setattr("red_pill.config.JOB_STALL_LIMIT", 3, raising=False)
	state = tmp_path / "state.json"
	state.write_text(json.dumps({"epoch": 7}))
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "epoch"},
	}

	driver = _bind(ScriptJobDriver())
	checkpoint = driver.step(payload, {}).new_checkpoint
	checkpoint = driver.step(payload, checkpoint).new_checkpoint

	with pytest.raises(RuntimeError, match="sin progreso"):
		driver.step(payload, checkpoint)


def test_watchdog_can_be_disabled_for_static_checkpoints(tmp_path):
	state = tmp_path / "state.json"
	state.write_text(json.dumps({"epoch": 7}))
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "epoch"},
		"watchdog": False,
	}

	driver = _bind(ScriptJobDriver())
	checkpoint: Dict[str, Any] = {}
	for _ in range(5):
		checkpoint = driver.step(payload, checkpoint).new_checkpoint  # No revienta


# ── Tokenización y rutas (D8) ──────────────────────────────────────────────


def test_step_command_tokenization_string_and_list(tmp_path):
	"""shlex sin shell; la forma lista pasa tal cual. Nada de shell=True implícito."""
	driver = _bind(ScriptJobDriver())
	payload = {"cwd": str(tmp_path), "step_command": "  echo   'hola mundo'  "}
	assert driver._build_argv(payload, str(tmp_path)) == ["echo", "hola mundo"]

	payload_list = {"cwd": str(tmp_path), "step_command": ["sh", "-c", "echo a | wc -l"]}
	assert driver._build_argv(payload_list, str(tmp_path)) == ["sh", "-c", "echo a | wc -l"]


def test_relative_binary_is_resolved_against_cwd(tmp_path):
	"""Lección de cdd35e0: systemd-run no resuelve rutas relativas por su cuenta."""
	venv_bin = tmp_path / ".venv" / "bin"
	venv_bin.mkdir(parents=True)
	(venv_bin / "python").write_text("#!/bin/sh\n")

	argv = _bind(ScriptJobDriver())._build_argv({"step_command": ".venv/bin/python train.py"}, str(tmp_path))

	assert argv[0] == os.path.abspath(venv_bin / "python")
	assert os.path.isabs(argv[0])


def test_venv_symlink_interpreter_is_not_followed(tmp_path):
	"""Lección del job ef18de08 (2026-07-28): el python de un venv es un symlink
	al intérprete base. Seguirlo con resolve() lo saca del venv (pyvenv.cfg se
	localiza por la ruta invocada) y el step muere con ModuleNotFoundError de
	sus propias dependencias. El argv debe quedar absoluto pero SIN resolver."""
	system_python = tmp_path / "usr" / "python3"
	system_python.parent.mkdir(parents=True)
	system_python.write_text("#!/bin/sh\n")
	venv_bin = tmp_path / "proj" / ".venv" / "bin"
	venv_bin.mkdir(parents=True)
	(venv_bin / "python").symlink_to(system_python)

	cwd = str(tmp_path / "proj")
	argv = _bind(ScriptJobDriver())._build_argv({"step_command": ".venv/bin/python train.py"}, cwd)

	assert argv[0] == str(venv_bin / "python"), "el symlink del venv debe invocarse por SU ruta"
	assert argv[0] != str(system_python.resolve())


def test_scope_carries_name_memory_and_runtime_bound(tmp_path, monkeypatch):
	"""El scope con nombre determinista es lo que hace posibles `job kill` y RuntimeMaxSec."""
	monkeypatch.setattr(ScriptJobDriver, "_has_systemd", staticmethod(lambda: True))
	monkeypatch.setattr(ScriptJobDriver, "_clear_stale_scope", lambda self: None)

	driver = _bind(ScriptJobDriver(), timeout=900)
	argv = driver._build_argv({"step_command": "echo hi", "preflight": {"memory_max": "16G"}}, str(tmp_path))

	assert argv[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
	assert "--unit=redpill-job-job-1234" in argv  # id corto del job
	assert "MemoryMax=16G" in argv
	assert "RuntimeMaxSec=900" in argv


# ── Timeout adaptativo y forense (D5 / D10) ────────────────────────────────


def test_adaptive_timeout_bound_progression():
	"""Sin historial, cota generosa; con historial, adaptativa; por intento, duplicada."""
	import red_pill.config as cfg

	assert compute_step_timeout({}, None, 0) == cfg.JOB_STEP_TIMEOUT_DEFAULT
	assert compute_step_timeout({"control": {"max_step_minutes": 20}}, None, 0) == 1200

	# Con media observada manda max(FACTOR × EMA, FLOOR)
	assert compute_step_timeout({}, {"step_seconds_ema": 3600}, 0) == cfg.JOB_STEP_TIMEOUT_FACTOR * 3600
	assert compute_step_timeout({}, {"step_seconds_ema": 60}, 0) == cfg.JOB_STEP_TIMEOUT_FLOOR

	# Cada intento consumido duplica la cota: auto-cura el fallback GPU→CPU
	assert compute_step_timeout({"control": {"max_step_minutes": 10}}, None, 2) == 600 * 4


def test_step_ema_feeds_eta_only_when_total_is_known():
	first = update_step_ema({"current": 10, "total": 20}, 600)
	assert first["step_seconds_ema"] == 600
	assert first["eta_seconds"] == 6000  # 10 steps restantes × 600 s

	smoothed = update_step_ema({**first, "current": 11}, 1200)
	assert 600 < smoothed["step_seconds_ema"] < 1200  # Media móvil, no el último valor

	assert "eta_seconds" not in update_step_ema({"current": 4200}, 300)  # Sin total no hay ETA


def test_step_timeout_raises_with_forensics(tmp_path):
	"""El vencimiento es fallo real, pero con los datos para recalibrar la cota."""
	driver = ScriptJobDriver()
	driver.bind("job-abcd-ef01", attempts=0, step_timeout_s=1)
	payload = {"cwd": str(tmp_path), "step_command": _script(tmp_path, "import time; time.sleep(30)")}

	with pytest.raises(JobStepTimeout) as caught:
		driver.step(payload, {})

	forensics = caught.value.forensics()
	assert forensics["reason"] == "timeout"
	assert forensics["bound_s"] == 1
	assert forensics["attempt"] == 1


def test_timeout_leaves_triple_trace_and_escalates_only_at_the_third(queue, clean_registry, monkeypatch, isolated_state):
	"""D10: log + error_log + marca en checkpoint; aviso los dos primeros, dolor el tercero."""
	from red_pill.jobs.drivers import append_job_log

	reports, pains = [], []
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda jid, task, status, content: reports.append(status))
	monkeypatch.setattr("red_pill.core.queue_worker.report_pain", lambda msg: pains.append(msg))

	class TimingOutDriver(ResumableJobDriver):
		source = "test_timeout"

		def step(self, payload, checkpoint_data):
			raise JobStepTimeout(elapsed_s=7200, bound_s=3600, ema_s=1800, attempt=self.attempts + 1)

	register_driver(TimingOutDriver)
	job_id = queue.enqueue_task(source="test_timeout", payload={"title": "colgado"})

	for expected_attempt in (1, 2, 3):
		process_driver_jobs(queue)
		task = queue.get_task(job_id)
		assert task["attempts"] == expected_attempt

	# 1) rastro en el log del job, 2) en error_log, 3) en la marca del checkpoint
	log_text = (isolated_state / "jobs" / f"{job_id[:8]}.log").read_text(encoding="utf-8")
	assert "STEP TIMEOUT" in log_text
	assert "STEP TIMEOUT" in task["error_log"]
	assert task["checkpoint_data"]["dirty_kill"]["reason"] == "timeout"
	assert task["checkpoint_data"]["dirty_kill"]["bound_s"] == 3600

	# Escalada: aviso, aviso, y solo entonces disyuntor + señal de dolor
	assert reports == ["warning", "warning", "failed"]
	assert len(pains) == 1
	assert task["status"] == "FRUSTRATED"

	append_job_log(job_id, "fin de la prueba")


# ── Kill del operador (D1) ─────────────────────────────────────────────────


def test_kill_marks_paused_with_dirty_flag_and_keeps_checkpoint(queue):
	job_id = queue.enqueue_task(source="script_job", payload={"title": "entrenamiento"})
	queue.save_checkpoint(job_id, {"epoch": 41}, {"current": 41})

	assert queue.kill_task(job_id) is True
	task = queue.get_task(job_id)

	assert task["status"] == "PAUSED"  # Mismo verbo para reanudar: no hay estado nuevo
	assert task["checkpoint_data"]["epoch"] == 41  # El avance sobrevive
	assert task["checkpoint_data"]["dirty_kill"]["reason"] == "operator"
	assert queue.list_tasks()[0]["dirty_kill"] == "operator"  # `job list` lo muestra como PAUSED*


def test_kill_discard_is_a_dead_letter_not_a_deletion(queue):
	job_id = queue.enqueue_task(source="script_job", payload={"title": "abortado"})

	queue.kill_task(job_id, discard=True)
	task = queue.get_task(job_id)

	assert task["status"] == "FRUSTRATED"
	assert "cancelled by operator" in task["error_log"]  # Trazabilidad > limpieza inmediata


def test_operator_kill_is_not_a_failure_for_the_runner(queue, clean_registry, monkeypatch):
	"""El orden del kill (sellar PAUSED antes de abatir) impide quemar el disyuntor."""
	reports = []
	monkeypatch.setattr("red_pill.core.queue_worker._report_job", lambda jid, task, status, content: reports.append(status))

	class KilledMidStepDriver(ResumableJobDriver):
		source = "test_killed"

		def step(self, payload, checkpoint_data):
			# El CLI ya selló el estado; el proceso muere y el step revienta.
			queue.kill_task(self.job_id)
			raise RuntimeError("step_command falló (rc=-15)")

	register_driver(KilledMidStepDriver)
	job_id = queue.enqueue_task(source="test_killed", payload={})

	process_driver_jobs(queue)
	task = queue.get_task(job_id)

	assert task["attempts"] == 0  # Ni un intento quemado
	assert task["status"] == "PAUSED"
	assert reports == []  # Ni una alarma falsa


def test_dirty_resume_validates_state_before_relaunching(tmp_path):
	"""Tras una interrupción dura no se reinicia en silencio: se valida o se falla con motivo."""
	driver = _bind(ScriptJobDriver())
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "epoch"},
	}

	# Había avance (época 12) pero el checkpoint del satélite no está: sospechoso.
	with pytest.raises(RuntimeError, match="reanudación sucia"):
		driver.step(payload, {"dirty_kill": {"reason": "operator"}, "epoch": 12})

	(tmp_path / "state.json").write_text("{ truncado a medias")
	with pytest.raises(RuntimeError, match="corrupto"):
		driver.step(payload, {"dirty_kill": {"reason": "timeout"}, "epoch": 12})


def test_dirty_resume_without_previous_progress_starts_clean(tmp_path):
	"""Un kill durante el PRIMER step no deja checkpoint, y eso es normal: se arranca de cero."""
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "import json, pathlib; pathlib.Path('state.json').write_text(json.dumps({'epoch': 1}))"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "epoch"},
	}

	outcome = _bind(ScriptJobDriver()).step(payload, {"dirty_kill": {"reason": "operator"}})

	assert outcome.progress["current"] == 1
	assert "dirty_kill" not in outcome.new_checkpoint


def test_dirty_marker_clears_after_a_good_step(tmp_path):
	"""La marca vive hasta el primer step reanudado con éxito, y desaparece sola."""
	(tmp_path / "state.json").write_text(json.dumps({"epoch": 12}))
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, "pass"),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "epoch"},
	}

	outcome = _bind(ScriptJobDriver()).step(payload, {"dirty_kill": {"reason": "operator"}, "epoch": 12})

	assert "dirty_kill" not in outcome.new_checkpoint
	assert outcome.new_checkpoint["epoch"] == 12


# ── Logs por job (D7) ──────────────────────────────────────────────────────


def test_child_output_lands_in_the_job_log(tmp_path, isolated_state):
	driver = _bind(ScriptJobDriver())
	command = _script(tmp_path, "print('linea de entrenamiento'); import sys; print('a stderr', file=sys.stderr)")

	driver.step({"cwd": str(tmp_path), "step_command": command}, {})

	log_text = (isolated_state / "jobs" / "job-1234.log").read_text(encoding="utf-8")
	assert "linea de entrenamiento" in log_text
	assert "a stderr" in log_text  # stderr redirigido al mismo sitio
	assert "===== step" in log_text  # Separador por step, con intento y cota


# ── Teardown y encadenado (§7 / §4b) ───────────────────────────────────────


def test_teardown_runs_on_every_exit_including_deferral(queue, clean_registry, monkeypatch):
	"""El caso crítico: un job que cede ante el sueño no puede dejar el residente descargado."""
	from red_pill.jobs.drivers import JobDeferred

	calls = []

	class TeardownDriver(ResumableJobDriver):
		source = "test_teardown"

		def step(self, payload, checkpoint_data):
			if payload["outcome"] == "defer":
				raise JobDeferred("VRAM ocupada")
			if payload["outcome"] == "fail":
				raise RuntimeError("boom")
			return StepOutcome(completed=True, new_checkpoint={}, summary="ok")

		def teardown(self, payload):
			calls.append(payload["outcome"])

	register_driver(TeardownDriver)
	for outcome in ("complete", "defer", "fail"):
		queue.enqueue_task(source="test_teardown", payload={"outcome": outcome})

	process_driver_jobs(queue)

	assert sorted(calls) == ["complete", "defer", "fail"]


def test_dag_chain_runs_in_one_invocation(queue, clean_registry):
	"""§4b: el hilo del runner encadena — sin esperar al siguiente tick del timer."""
	executed = []

	class ChainDriver(ResumableJobDriver):
		source = "test_chain"

		def step(self, payload, checkpoint_data):
			executed.append(payload["name"])
			return StepOutcome(completed=True, new_checkpoint={}, summary=payload["name"])

	register_driver(ChainDriver)
	parent = queue.enqueue_task(source="test_chain", payload={"name": "fase-1"})
	child = queue.enqueue_task(source="test_chain", payload={"name": "fase-2"}, parent_task_id=parent)

	assert queue.get_task(child)["status"] == "BLOCKED"

	completed = process_driver_jobs(queue)  # UNA sola invocación

	assert executed == ["fase-1", "fase-2"]
	assert completed == 2
	assert queue.get_task(child)["status"] == "COMPLETED"


def test_preflight_unload_uses_configured_proxy_and_tolerates_it_being_down(monkeypatch):
	"""D2/D8: la URL sale de config (nunca a fuego) y un proxy caído no rompe el step."""
	import red_pill.config as cfg

	called = {}
	monkeypatch.setattr(ScriptJobDriver, "_request_vram_unload", staticmethod(lambda url: called.setdefault("url", url)))
	monkeypatch.setattr("red_pill.core.vram_probe.VramProbe.get_free_mb", lambda: 8000)

	ScriptJobDriver().preflight({"preflight": {"vram_unload": True, "min_free_vram_mb": 3500}})

	assert called["url"] == cfg.DUAL_BIND_PROXY_URL

	# Proxy inalcanzable: se registra y se sigue (el probe decide de verdad)
	ScriptJobDriver._request_vram_unload("http://127.0.0.1:1")


def test_preflight_defers_without_burning_attempts_when_vram_is_short(queue, clean_registry, monkeypatch):
	monkeypatch.setattr("red_pill.core.vram_probe.VramProbe.get_free_mb", lambda: 500)
	register_driver(ScriptJobDriver)
	job_id = queue.enqueue_task(
		source="script_job",
		payload={"step_command": "echo hi", "preflight": {"min_free_vram_mb": 3500}},
	)
	queue.save_checkpoint(job_id, {"epoch": 9}, None)

	process_driver_jobs(queue)
	task = queue.get_task(job_id)

	assert task["status"] == "PENDING"
	assert task["attempts"] == 0  # R1: el entorno no quema el disyuntor
	assert task["checkpoint_data"]["epoch"] == 9


# ── Recetas YAML: la forma humana de encolar (27 jul) ──────────────────────


def _write_recipe(root, body: str, where: str = "configs/jobs"):
	recipe_dir = root / where
	recipe_dir.mkdir(parents=True, exist_ok=True)
	path = recipe_dir / "school.yaml"
	path.write_text(body, encoding="utf-8")
	return path


def test_recipe_carries_the_payload_and_infers_the_project_root(tmp_path):
	"""La receta vive en el satélite; cwd se deduce de dónde está el fichero."""
	from red_pill.jobs.recipes import load_recipe

	project = tmp_path / "frankenswarm"
	_write_recipe(
		project,
		"""
source: script_job
title: Escuela
priority: 7
step_command: .venv/bin/python train.py
checkpoint_file: storage/state.json
progress:
  mode: bounded
  current_key: current_epoch
  total: 1408
completion:
  key: milestones_achieved
  contains: 8_years
control:
  max_step_minutes: 780
""",
	)

	source, payload, priority, parent, _s = load_recipe(str(project / "configs" / "jobs" / "school.yaml"))

	assert (source, priority, parent) == ("script_job", 7, None)
	assert payload["cwd"] == str(project)  # deducido, no repetido en el YAML
	assert payload["completion"] == {"key": "milestones_achieved", "contains": "8_years"}
	assert payload["control"]["max_step_minutes"] == 780
	ScriptJobDriver.validate(payload)  # una receta válida produce un payload válido


def test_recipe_short_name_resolves_walking_up_the_workspace(tmp_path):
	"""`--recipe school` desde cualquier subdirectorio del proyecto."""
	from red_pill.jobs.recipes import load_recipe, resolve_recipe_path

	project = tmp_path / "frankenswarm"
	expected = _write_recipe(project, "source: script_job\nstep_command: echo hi\n")
	deep = project / "src" / "bitnet" / "training"
	deep.mkdir(parents=True)

	assert resolve_recipe_path("school", base_dir=deep) == expected.resolve()

	source, payload, _, _, _s = load_recipe("school", base_dir=deep)
	assert source == "script_job"
	assert payload["title"] == "school"  # sin title explícito, el nombre del fichero


def test_recipe_without_source_is_rejected(tmp_path):
	from red_pill.jobs.recipes import load_recipe

	project = tmp_path / "proyecto"
	_write_recipe(project, "title: sin source\nstep_command: echo hi\n")

	with pytest.raises(ValueError, match="source"):
		load_recipe(str(project / "configs" / "jobs" / "school.yaml"))


def test_missing_recipe_names_where_it_looked(tmp_path):
	from red_pill.jobs.recipes import resolve_recipe_path

	with pytest.raises(FileNotFoundError, match="school"):
		resolve_recipe_path("school", base_dir=tmp_path)


# ── Cadencia real de checkpoint (medida, no supuesta) ──────────────────────


def test_checkpoint_cadence_is_measured_during_the_step(tmp_path):
	"""Lo que importa no es cuánto vive el proceso, sino cada cuánto deja avance.

	Un step con varios guardados internos se mide por sus intervalos reales; si el
	mtime solo se comparase entre steps, la cadencia se inflaría hasta el step entero.
	"""
	state = tmp_path / "state.json"
	body = f"""
import json, pathlib, time
p = pathlib.Path({str(state)!r})
for i in range(3):
	time.sleep(0.4)
	d = json.loads(p.read_text()) if p.exists() else {{"epoch": 0}}
	d["epoch"] += 1
	p.write_text(json.dumps(d))
"""
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, body),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "epoch"},
	}

	driver = _bind(ScriptJobDriver())
	outcome = driver.step(payload, {})

	# Tres guardados dentro de un mismo step: la unidad recuperable es la época,
	# no el step — señal de que este trabajo SÍ podría trocearse.
	assert outcome.progress["checkpoint_writes_in_step"] >= 2
	assert outcome.progress["checkpoint_interval_s"] >= 0


def test_single_write_means_the_step_is_the_recoverable_unit(tmp_path):
	"""Un solo guardado por step: interrumpir cuesta el step entero (caso de la escuela)."""
	state = tmp_path / "state.json"
	body = f"""
import json, pathlib, time
time.sleep(0.6)
pathlib.Path({str(state)!r}).write_text(json.dumps({{"epoch": 1}}))
"""
	payload = {
		"cwd": str(tmp_path),
		"step_command": _script(tmp_path, body),
		"checkpoint_file": "state.json",
		"progress": {"mode": "unbounded", "current_key": "epoch"},
	}

	outcome = _bind(ScriptJobDriver()).step(payload, {})

	assert outcome.progress["checkpoint_writes_in_step"] == 1
	assert outcome.progress["checkpoint_interval_s"] >= 0


def test_local_unversioned_recipe_overrides_the_versioned_one(tmp_path):
	"""`.red-pill/jobs/` es estado del kernel: sirve de override sin ensuciar el repo."""
	from red_pill.jobs.recipes import load_recipe

	project = tmp_path / "frankenswarm"
	_write_recipe(project, "source: script_job\ntitle: versionada\nstep_command: echo hi\n")
	_write_recipe(project, "source: script_job\ntitle: local\nstep_command: echo hi\n", where=".red-pill/jobs")

	_, payload, _, _, _s = load_recipe("school", base_dir=project)

	assert payload["title"] == "local"
	assert payload["cwd"] == str(project)  # la raíz se deduce igual en ambos sitios
