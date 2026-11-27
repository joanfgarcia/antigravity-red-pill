"""Fase 0 de VRAM: pausa del modelo del desk (ocioso) y devolución en teardown.

Caso real (ciclo 8a315ef2, 2026-11-27): el desk legítimo (Spark en
`dokime-llama`) retenía 4,4 GB, el 27B de distill no cupo y los 60 pasos del
nocturno devolvieron 503. El daemon no puede compartir esa VRAM (es otro
proceso), así que el arbitraje mínimo es: parar el desk si está ocioso y
devolverlo al terminar.
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone

import pytest
import yaml

from red_pill.core import gpu_desk


class FakePodman:
	"""Sustituto de `gpu_desk._podman` con estado mínimo y registro de llamadas."""

	def __init__(self, *, exists=True, running=True, last_ts=None, stop_ok=True, start_ok=True):
		self.state = {"exists": exists, "running": running}
		self.last_ts = time.time() - 3600 if last_ts is None else last_ts
		self.stop_ok = stop_ok
		self.start_ok = start_ok
		self.calls: list[list[str]] = []

	def __call__(self, args, timeout=30):
		self.calls.append(list(args))
		verb = args[0]
		if verb == "container" and args[1] == "exists":
			return subprocess.CompletedProcess(args, 0 if self.state["exists"] else 1, "", "")
		if verb == "inspect":
			return subprocess.CompletedProcess(args, 0, "true" if self.state["running"] else "false", "")
		if verb == "logs":
			ts = datetime.fromtimestamp(self.last_ts, tz=timezone.utc).isoformat()
			return subprocess.CompletedProcess(args, 0, f"{ts} slot release: id 0\n", "")
		if verb == "stop":
			self.state["running"] = False
			return subprocess.CompletedProcess(args, 0 if self.stop_ok else 1, "", "" if self.stop_ok else "boom")
		if verb == "start":
			self.state["running"] = True
			return subprocess.CompletedProcess(args, 0 if self.start_ok else 1, "", "" if self.start_ok else "boom")
		return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
	monkeypatch.setattr(gpu_desk, "get_state_dir", lambda: tmp_path)
	return tmp_path


def test_pause_if_idle_para_y_guarda_estado(state_dir, monkeypatch):
	fake = FakePodman()
	monkeypatch.setattr(gpu_desk, "_podman", fake)

	assert gpu_desk.pause_if_idle(600, "job-1") is True
	state = gpu_desk.load_state()
	assert state["job_id"] == "job-1"
	assert state["container"] == "dokime-llama"
	assert ["stop", "dokime-llama"] in fake.calls


def test_pause_no_toca_un_desk_activo(state_dir, monkeypatch):
	fake = FakePodman(last_ts=time.time() - 30)  # hace 30 s
	monkeypatch.setattr(gpu_desk, "_podman", fake)

	assert gpu_desk.pause_if_idle(600, "job-1") is False
	assert gpu_desk.load_state() is None
	assert not any(c[0] == "stop" for c in fake.calls)


def test_pause_sin_lectura_de_actividad_no_para(state_dir, monkeypatch):
	fake = FakePodman()
	fake.last_ts = None

	def no_time(args, timeout=30):
		fake.calls.append(list(args))
		if args[0] == "logs":
			return subprocess.CompletedProcess(args, 0, "sin marca de tiempo\n", "")
		return FakePodman.__call__(fake, args, timeout)

	monkeypatch.setattr(gpu_desk, "_podman", no_time)
	assert gpu_desk.pause_if_idle(600, "job-1") is False
	assert gpu_desk.load_state() is None


def test_pause_no_pisa_la_pausa_de_otro_job(state_dir, monkeypatch):
	monkeypatch.setattr(gpu_desk, "_podman", FakePodman(running=False))
	assert gpu_desk.pause_if_idle(600, "job-a") is False

	# El desk sigue parado (lo paró job-a) y llega job-b: no debe escribir estado.
	fake = FakePodman(running=False)
	monkeypatch.setattr(gpu_desk, "_podman", fake)
	gpu_desk._save_state({"container": "dokime-llama", "job_id": "job-a", "stopped_at": time.time()})
	assert gpu_desk.pause_if_idle(600, "job-b") is False
	assert gpu_desk.load_state()["job_id"] == "job-a"


def test_resume_solo_devuelve_lo_que_paro_ese_job(state_dir, monkeypatch):
	fake = FakePodman(running=False)
	monkeypatch.setattr(gpu_desk, "_podman", fake)
	gpu_desk._save_state({"container": "dokime-llama", "job_id": "job-1", "stopped_at": time.time()})

	assert gpu_desk.resume(job_id="otro") is False
	assert fake.state["running"] is False
	assert gpu_desk.resume(job_id="job-1") is True
	assert fake.state["running"] is True
	assert gpu_desk.load_state() is None


def test_resume_no_arranca_si_ya_corre(state_dir, monkeypatch):
	fake = FakePodman(running=True)
	monkeypatch.setattr(gpu_desk, "_podman", fake)
	gpu_desk._save_state({"container": "dokime-llama", "job_id": "job-1", "stopped_at": time.time()})

	assert gpu_desk.resume(job_id="job-1") is False
	assert gpu_desk.load_state() is None  # estado limpiado, contenedor intacto


# ── Integración con el DAG ──────────────────────────────────────────────────
def _payload(**extra):
	base = {
		"manifest": {"stages": []},
		"cwd": ".",
		"workdir": ".",
		"min_vram_mb": 6000,
	}
	base.update(extra)
	return base


def _stage():
	return {"id": "distill", "type": "command", "minion": "command_runner", "command": "true", "requires_gpu": True}


def _offline_daemon(monkeypatch):
	"""Sin daemon en los tests: ni /status ni /v1/models salen del proceso."""
	monkeypatch.setattr("red_pill.jobs.drivers.dag.DagJobDriver._daemon_status", staticmethod(lambda: {}))
	monkeypatch.setattr("red_pill.metabolism.ephemeral_server._check_llm_available", lambda: False)


def test_preflight_pausa_el_desk_y_reanuda_la_medida(monkeypatch):
	from red_pill.jobs.drivers import dag_exec
	from red_pill.jobs.drivers.dag import DagJobDriver

	probes = iter([(True, 3000, -1), (True, 7000, -1)])
	monkeypatch.setattr(dag_exec, "_gpu_health_probe", lambda: next(probes))
	monkeypatch.setattr(dag_exec.time, "sleep", lambda _s: None)
	monkeypatch.setattr("red_pill.core.gpu_desk.pause_if_idle", lambda idle, job: True)
	_offline_daemon(monkeypatch)

	d = DagJobDriver()
	d.job_id = "job-1"
	d._preflight_stage_gpu(_stage(), "distill", _payload(gpu_desk_preempt=True))


def test_preflight_difiere_si_el_desk_no_esta_ocioso(monkeypatch):
	from red_pill.jobs.drivers import dag_exec
	from red_pill.jobs.drivers.base import JobDeferred
	from red_pill.jobs.drivers.dag import DagJobDriver

	monkeypatch.setattr(dag_exec, "_gpu_health_probe", lambda: (True, 3000, -1))
	monkeypatch.setattr("red_pill.core.gpu_desk.pause_if_idle", lambda idle, job: False)
	_offline_daemon(monkeypatch)

	d = DagJobDriver()
	d.job_id = "job-1"
	with pytest.raises(JobDeferred):
		d._preflight_stage_gpu(_stage(), "distill", _payload(gpu_desk_preempt=True))


def test_preflight_no_pausa_sin_opt_in(monkeypatch):
	"""Un bench que MIDE el desk no lleva la clave: nunca lo pausa."""
	from red_pill.jobs.drivers import dag_exec
	from red_pill.jobs.drivers.base import JobDeferred
	from red_pill.jobs.drivers.dag import DagJobDriver

	calls = []
	monkeypatch.setattr(dag_exec, "_gpu_health_probe", lambda: (True, 3000, -1))
	monkeypatch.setattr("red_pill.core.gpu_desk.pause_if_idle", lambda idle, job: calls.append(job) or True)
	_offline_daemon(monkeypatch)

	d = DagJobDriver()
	d.job_id = "job-bench"
	with pytest.raises(JobDeferred):
		d._preflight_stage_gpu(_stage(), "distill", _payload())
	assert calls == []


def test_teardown_no_devuelve_el_desk_si_el_job_sigue_vivo(monkeypatch):
	from red_pill.jobs.drivers.dag import DagJobDriver

	resumed = []
	monkeypatch.setattr(
		"red_pill.core.gpu_desk.load_state",
		lambda: {"container": "dokime-llama", "job_id": "job-1", "stopped_at": time.time()},
	)
	monkeypatch.setattr("red_pill.core.gpu_desk.resume", lambda job_id=None: resumed.append(job_id) or True)

	class _Queue:
		def get_task(self, _job_id):
			return {"status": "PROCESSING"}

	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager", lambda: _Queue())
	d = DagJobDriver()
	d.job_id = "job-1"
	d.teardown(_payload(gpu_desk_preempt=True))
	assert resumed == []

	class _QueueDone(_Queue):
		def get_task(self, _job_id):
			return {"status": "COMPLETED"}

	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager", lambda: _QueueDone())
	d.teardown(_payload(gpu_desk_preempt=True))
	assert resumed == ["job-1"]


def test_nightly_declara_la_pausa_del_desk():
	payload = yaml.safe_load(open("configs/jobs/nightly.yaml", encoding="utf-8"))
	assert payload["gpu_desk_preempt"] is True
	assert int(payload["gpu_desk_idle_s"]) >= 300


def _pin_profile_requirements(monkeypatch, required_mb=6500, freeable_mb=3500):
	from red_pill.jobs.drivers.dag import DagJobDriver

	monkeypatch.setattr(DagJobDriver, "_stage_required_profile", staticmethod(lambda _s: "bonsai_25_27b_distill"))
	monkeypatch.setattr(DagJobDriver, "_stage_required_vram_mb", classmethod(lambda _cls, _s: required_mb))
	monkeypatch.setattr(DagJobDriver, "_resident_freeable_mb", classmethod(lambda _cls, _st, _req: freeable_mb))


def test_preflight_cuenta_la_vram_del_modelo_residente(monkeypatch):
	"""Un k2 residente de 3,5 GB hace sitio al 27B tras el swap: no se difiere
	(y tampoco se toca el desk)."""
	from red_pill.jobs.drivers import dag_exec
	from red_pill.jobs.drivers.dag import DagJobDriver

	paused = []
	_pin_profile_requirements(monkeypatch, required_mb=6500, freeable_mb=3500)
	monkeypatch.setattr(dag_exec, "_gpu_health_probe", lambda: (True, 3000, -1))
	monkeypatch.setattr("red_pill.core.gpu_desk.pause_if_idle", lambda idle, job: paused.append(job) or True)
	monkeypatch.setattr(
		DagJobDriver,
		"_daemon_status",
		staticmethod(lambda: {"loaded_profile": "k2_horizon_7b", "mode": "gpu", "n_ctx": 10240}),
	)

	d = DagJobDriver()
	d.job_id = "job-1"
	d._preflight_stage_gpu(_stage(), "distill", _payload(gpu_desk_preempt=True))
	assert paused == []


def test_preflight_difiere_si_ni_el_swap_ni_el_desk_dan_sitio(monkeypatch):
	from red_pill.jobs.drivers import dag_exec
	from red_pill.jobs.drivers.base import JobDeferred
	from red_pill.jobs.drivers.dag import DagJobDriver

	_pin_profile_requirements(monkeypatch, required_mb=6500, freeable_mb=3500)
	monkeypatch.setattr(dag_exec, "_gpu_health_probe", lambda: (True, 2000, -1))
	monkeypatch.setattr("red_pill.core.gpu_desk.pause_if_idle", lambda idle, job: False)
	monkeypatch.setattr(
		DagJobDriver,
		"_daemon_status",
		staticmethod(lambda: {"loaded_profile": "k2_horizon_7b", "mode": "gpu", "n_ctx": 10240}),
	)

	d = DagJobDriver()
	d.job_id = "job-1"
	with pytest.raises(JobDeferred) as exc:
		d._preflight_stage_gpu(_stage(), "distill", _payload(gpu_desk_preempt=True))
	assert "liberables" in str(exc.value)


def test_resident_freeable_mb_estima_por_el_perfil_cargado(monkeypatch):
	from red_pill.core.model_registry import ModelRegistry
	from red_pill.jobs.drivers.dag import DagJobDriver

	seen = {}

	def _plan(profile, ctx=None, free_mb=None):
		seen["profile"] = profile
		seen["ctx"] = ctx
		return {"fits": False, "tried": [{"required_mb": 4100}, {"required_mb": 3200}]}

	monkeypatch.setattr(ModelRegistry, "plan_kv_cache", classmethod(lambda cls, *a, **kw: _plan(*a, **kw)))
	got = DagJobDriver._resident_freeable_mb({"loaded_profile": "k2_horizon_7b", "n_ctx": 10240}, "bonsai_25_27b_distill")
	assert got == 4100  # el preferido (optimista), no el degradado
	assert seen == {"profile": "k2_horizon_7b", "ctx": 10240}
	assert DagJobDriver._resident_freeable_mb({"loaded_profile": "bonsai_25_27b_distill"}, "bonsai_25_27b_distill") == 0
