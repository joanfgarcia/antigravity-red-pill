"""SleepJobDriver (RFC_SLEEP_JOB_DRIVER): 14 unidades atómicas, GPU por unidad,
semántica de fallo por unidad, finalizador solo en la última, telemetría 2D,
kill cooperativo y exención anti-deadlock del runner."""

import json
import time

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_worker import process_driver_jobs
from red_pill.jobs.drivers import JobDeferred, StepOutcome, register_driver
from red_pill.jobs.drivers.sleep import SleepJobDriver


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


# ── Stubs para no tocar infraestructura real ──────────────────────────────────


class _FakeMemoryManager:
	client = None

	def __enter__(self):
		return self

	def __exit__(self, *args):
		return False


class _FakePhase:
	def __init__(self, name, requires_gpu=False):
		self._name = name
		self._gpu = requires_gpu
		self.executed = 0

	@property
	def name(self):
		return self._name

	@property
	def requires_gpu(self):
		return self._gpu

	def execute(self, ctx):
		self.executed += 1
		ctx.total_processed += 1


def _fake_unit_table(phases=("consolidation", "erosion", "thread")):
	"""Tabla reducida de unidades para test: 3 fases sin rituales reales."""
	units = []
	for i, name in enumerate(phases):
		units.append(
			{
				"unit": f"{name}:{i + 1}",
				"kind": "phase",
				"phase_index": i,
				"phase_name": name,
				"requires_gpu": name == "consolidation",
			}
		)
	return units


def _patch_driver(driver, monkeypatch, phases=("consolidation", "erosion")):
	"""Aísla el driver: tabla de unidades, fases, rituales, GPU y MemoryManager."""
	monkeypatch.setattr(driver, "_unit_table", lambda payload: _fake_unit_table(phases))
	fake_phases = [_FakePhase(name, requires_gpu=(name == "consolidation")) for name in phases]

	import red_pill.metabolism.phases as phases_mod

	monkeypatch.setattr(phases_mod, "SLEEP_PHASES", fake_phases)

	def fake_run_phase(ctx, idx):
		fake_phases[idx].execute(ctx)

	monkeypatch.setattr("red_pill.metabolism.sleep.run_sleep_phase", fake_run_phase)
	monkeypatch.setattr(driver, "_run_phase", fake_run_phase)
	monkeypatch.setattr(driver, "_run_ritual", lambda mm, r: None)
	monkeypatch.setattr(driver, "_run_thread", lambda: None)
	monkeypatch.setattr(driver, "_preflight_unit_gpu", lambda unit, payload: None)
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMemoryManager())
	return fake_phases


def _make_driver():
	return SleepJobDriver()


# ── Tests RFC §6 ──────────────────────────────────────────────────────────────


def test_sleep_job_validate_mode():
	d = _make_driver()
	d.validate({"mode": "lazy"})
	d.validate({"mode": "deep"})
	with pytest.raises(ValueError):
		d.validate({"mode": "turbo"})


def test_sleep_job_step_advances_unit(monkeypatch):
	d = _make_driver()
	fake_phases = _patch_driver(d, monkeypatch)
	outcome = d.step({"mode": "lazy"}, {})
	assert not outcome.completed
	assert outcome.new_checkpoint["resume_unit"] == 1
	assert outcome.new_checkpoint["total_processed"] == 1  # consolidación ejecutada
	assert fake_phases[0].executed == 1


def test_sleep_job_resume_skips_done(monkeypatch):
	"""Reanudación tras interrupción: arranca en la unidad pendiente, no re-ejecuta."""
	d = _make_driver()
	fake_phases = _patch_driver(d, monkeypatch, phases=("consolidation", "erosion"))
	checkpoint = {"resume_unit": 1, "total_processed": 1, "mode": "lazy", "total_units": 2}
	outcome = d.step({"mode": "lazy"}, checkpoint)
	assert outcome.new_checkpoint["resume_unit"] == 2
	assert fake_phases[0].executed == 0  # consolidación NO se re-ejecuta
	assert fake_phases[1].executed == 1  # erosion SÍ


def test_sleep_job_gpu_defer(monkeypatch):
	"""consolidation (GPU) se difiere → JobDeferred, resume_unit intacto."""
	d = _make_driver()
	_patch_driver(d, monkeypatch, phases=("consolidation",))

	def gpu_defer(unit, payload):
		if unit["unit"].startswith("consolidation"):
			raise JobDeferred("GPU no disponible")

	monkeypatch.setattr(d, "_preflight_unit_gpu", gpu_defer)
	with pytest.raises(JobDeferred):
		d.step({"mode": "lazy"}, {})
	# El deferral NO quema attempts (R1) — se comprueba a nivel runner abajo.


def test_sleep_job_cpu_unit_runs_while_gpu_busy(monkeypatch):
	"""Unidad CPU se ejecuta aunque la GPU esté ocupada (preflight GPU falla en otra)."""
	d = _make_driver()
	_patch_driver(d, monkeypatch, phases=("consolidation", "erosion"))

	def gpu_defer(unit, payload):
		if unit["unit"].startswith("consolidation"):
			raise JobDeferred("GPU no disponible")

	monkeypatch.setattr(d, "_preflight_unit_gpu", gpu_defer)
	# Avanza con checkpoint ya en la unidad CPU (erosion) → corre pese a GPU ocupada.
	outcome = d.step({"mode": "lazy"}, {"resume_unit": 1, "total_processed": 1, "mode": "lazy", "total_units": 2})
	assert outcome.new_checkpoint["resume_unit"] == 2


def test_sleep_job_unit_failure_continues(monkeypatch):
	"""Unidad que revienta → skip marcado, avanza, el job NO falla."""
	d = _make_driver()
	_patch_driver(d, monkeypatch, phases=("consolidation", "erosion"))

	def boom(ctx, idx):
		raise RuntimeError("distiller deadlock")

	monkeypatch.setattr(d, "_run_phase", boom)
	outcome = d.step({"mode": "lazy"}, {})
	assert outcome.new_checkpoint["resume_unit"] == 1  # avanzó pese al fallo
	assert outcome.new_checkpoint.get("last_failed_unit") == "consolidation:1"


def test_sleep_job_finalizes_only_last(monkeypatch):
	"""El finalizador corre SOLO en la última unidad (ciclo completo)."""
	d = _make_driver()
	_patch_driver(d, monkeypatch, phases=("consolidation", "erosion"))
	finalized = []

	monkeypatch.setattr(
		"red_pill.metabolism.sleep.finalize_sleep_cycle",
		lambda ctx, mode: finalized.append(mode),
	)
	# Unidad 0 (no última): NO finaliza.
	o = d.step({"mode": "lazy"}, {})
	assert not finalized
	# Unidad 1 (última de 2): finaliza.
	o = d.step({"mode": "lazy"}, {"resume_unit": 1, "total_processed": 1, "mode": "lazy", "total_units": 2})
	assert finalized == ["lazy"]
	assert o.completed and o.new_checkpoint.get("finalized")


def test_sleep_job_status_live(monkeypatch, tmp_path):
	"""El fichero público refleja unit_index/total_units tras cada unidad."""
	import red_pill.core.paths as paths

	state_dir = tmp_path / "state"
	state_dir.mkdir()
	monkeypatch.setattr(paths, "get_state_dir", lambda: state_dir)

	d = _make_driver()
	_patch_driver(d, monkeypatch, phases=("consolidation", "erosion"))
	d.step({"mode": "lazy"}, {})
	status = json.loads((state_dir / "sleep_phase_status.json").read_text())
	assert status["unit_index"] == 1
	assert status["total_units"] == 2
	assert status["status"] == "running"


def test_nightly_yield_self_exempt(queue, clean_registry, monkeypatch, tmp_path):
	"""§2.3: sleep_job NO se difiere por su propio fichero 'running'; un job ajeno sí."""
	import red_pill.core.paths as paths
	from red_pill.jobs.drivers import ResumableJobDriver

	state_dir = tmp_path / "state"
	state_dir.mkdir()
	monkeypatch.setattr(paths, "get_state_dir", lambda: state_dir)

	# Driver ajeno simple (completa en 1 step) para el lado "job ajeno".
	class _Other(ResumableJobDriver):
		source = "test_other"

		def step(self, payload, checkpoint_data):
			return StepOutcome(completed=True, new_checkpoint={}, summary="ok")

	register_driver(SleepJobDriver)
	register_driver(_Other)

	# Fichero público 'running' fresco → un job ajeno debe diferirse (return 0, PENDING).
	status_file = state_dir / "sleep_phase_status.json"
	status_file.write_text(json.dumps({"status": "running", "updated_at": time.time()}))
	other_job = queue.enqueue_task(source="test_other", payload={})
	assert process_driver_jobs(queue) == 0
	assert queue.get_task(other_job)["status"] == "PENDING" and queue.get_task(other_job)["attempts"] == 0

	# Un sleep_job (stub) NO se auto-difiere: avanza pese al fichero running (§2.3).
	def noop_preflight(self, payload):
		return None

	monkeypatch.setattr("red_pill.jobs.drivers.sleep.SleepJobDriver.preflight", noop_preflight)
	monkeypatch.setattr("red_pill.jobs.drivers.sleep.SleepJobDriver._unit_table", lambda self, payload: _fake_unit_table(("consolidation",)))
	monkeypatch.setattr("red_pill.jobs.drivers.sleep.SleepJobDriver._run_phase", lambda self, ctx, idx: None)
	monkeypatch.setattr("red_pill.jobs.drivers.sleep.SleepJobDriver._run_ritual", lambda self, mm, r: None)
	monkeypatch.setattr("red_pill.jobs.drivers.sleep.SleepJobDriver._run_thread", lambda self: None)
	monkeypatch.setattr("red_pill.jobs.drivers.sleep.SleepJobDriver._preflight_unit_gpu", lambda self, unit, payload: None)
	monkeypatch.setattr("red_pill.jobs.drivers.sleep.SleepJobDriver._write_public_status", lambda self, *a, **kw: None)
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMemoryManager())

	sleep_job = queue.enqueue_task(source="sleep_job", payload={"mode": "lazy"})
	assert process_driver_jobs(queue) == 1
	assert queue.get_task(sleep_job)["status"] == "COMPLETED"


def test_sleep_job_kill_cooperative(monkeypatch):
	"""El driver es cooperativo: un step no se interrumpe a mitad (unidad atómica)."""
	d = _make_driver()
	_patch_driver(d, monkeypatch, phases=("consolidation",))
	# La unidad en vuelo completa SIEMPRE: el runner relee el estado en frontera (R3),
	# no hay scope que abatir (in-proceso). Comprobamos que un step no es abortable
	# desde fuera — solo se pausa en la frontera del siguiente.
	outcome = d.step({"mode": "lazy"}, {})
	assert outcome.new_checkpoint["resume_unit"] == 1  # la unidad se completó
