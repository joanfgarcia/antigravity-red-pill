"""Tests de los minions de sleep (RFC_JOB_DAG §4.2 fleco 2): ritual/fase/finalize
como lógica pura consumida por el dag_job. Herramienta sin metabolismo real:
se mockea MemoryManager, rituals, SLEEP_PHASES y run_sleep_phase."""

import asyncio
import json

from red_pill.swarm.agents.sleep_minions import SleepFinalizeMinion, SleepPhaseMinion, SleepRitualMinion


def _run(coro):
	return asyncio.run(coro)


class _FakeMM:
	pass


class _FakePhase:
	def __init__(self, name):
		self.name = name


# ── SleepRitualMinion ─────────────────────────────────────────────────────────

def test_ritual_ok(monkeypatch):
	"""Ritual normal: ejecuta fn(MemoryManager()) y devuelve éxito."""
	called = {}

	async def _maintenance(mm):
		called["mm"] = mm

	monkeypatch.setattr("red_pill.rituals.maintenance_ritual", _maintenance)
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMM())

	m = SleepRitualMinion()
	res = _run(m.execute("", ritual="maintenance"))
	assert res["status"] == "success"
	assert res["ritual"] == "maintenance"
	assert called["mm"] is not None


def test_ritual_thread(monkeypatch):
	"""Ritual thread: ejecuta fn() SIN argumento."""
	called = []

	async def _thread():
		called.append(True)

	monkeypatch.setattr("red_pill.rituals.thread_ritual", _thread)

	m = SleepRitualMinion()
	res = _run(m.execute("", ritual="thread"))
	assert res["status"] == "success"
	assert called == [True]


def test_ritual_inexistente():
	"""Ritual que no existe → failed (sin lanzar)."""
	m = SleepRitualMinion()
	res = _run(m.execute("", ritual="no_existe"))
	assert res["status"] == "failed"
	assert "no existe" in res["error"]


def test_ritual_error(monkeypatch):
	"""El ritual lanza → failed con el error."""
	async def _boom(_mm):
		raise RuntimeError("ritual roto")

	monkeypatch.setattr("red_pill.rituals.maintenance_ritual", _boom)
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMM())

	m = SleepRitualMinion()
	res = _run(m.execute("", ritual="maintenance"))
	assert res["status"] == "failed"
	assert "ritual roto" in res["error"]


# ── SleepPhaseMinion ──────────────────────────────────────────────────────────

def test_phase_ok(monkeypatch):
	"""Fase válida: construye ctx con total previo y devuelve el nuevo total."""
	monkeypatch.setattr("red_pill.metabolism.phases.SLEEP_PHASES", [_FakePhase("consolidation")])
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMM())

	class _Ctx:
		def __init__(self, **kw):
			self.total_processed = kw.get("total_processed", 0)

	def _run_phase(ctx, phase_index):
		ctx.total_processed = 42

	monkeypatch.setattr("red_pill.metabolism.phases.base.SleepContext", _Ctx)
	monkeypatch.setattr("red_pill.metabolism.sleep.run_sleep_phase", _run_phase)

	m = SleepPhaseMinion()
	res = _run(m.execute("", phase_index=0))
	assert res["status"] == "success"
	assert res["phase"] == "consolidation"
	assert res["total_processed"] == 42


def test_phase_fuera_de_rango(monkeypatch):
	monkeypatch.setattr("red_pill.metabolism.phases.SLEEP_PHASES", [_FakePhase("consolidation")])
	m = SleepPhaseMinion()
	res = _run(m.execute("", phase_index=5))
	assert res["status"] == "failed"
	assert "fuera de rango" in res["error"]


def test_phase_error(monkeypatch):
	"""run_sleep_phase lanza → failed (sin lanzar)."""
	monkeypatch.setattr("red_pill.metabolism.phases.SLEEP_PHASES", [_FakePhase("consolidation")])
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMM())
	monkeypatch.setattr("red_pill.metabolism.phases.base.SleepContext", lambda **kw: _FakeMM())

	def _boom(ctx, phase_index):
		raise RuntimeError("fase rota")

	monkeypatch.setattr("red_pill.metabolism.sleep.run_sleep_phase", _boom)

	m = SleepPhaseMinion()
	res = _run(m.execute("", phase_index=0))
	assert res["status"] == "failed"
	assert "fase rota" in res["error"]


# ── SleepFinalizeMinion ───────────────────────────────────────────────────────

def test_finalize_ok(monkeypatch):
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMM())
	monkeypatch.setattr("red_pill.metabolism.phases.base.SleepContext", lambda **kw: _FakeMM())
	monkeypatch.setattr("red_pill.metabolism.sleep.finalize_sleep_cycle", lambda ctx, mode="lazy": 150)

	m = SleepFinalizeMinion()
	res = _run(m.execute(""))
	assert res["status"] == "success"
	assert res["total_processed"] == 150


def test_finalize_error(monkeypatch):
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: _FakeMM())
	monkeypatch.setattr("red_pill.metabolism.phases.base.SleepContext", lambda **kw: _FakeMM())

	def _boom(ctx, mode="lazy"):
		raise RuntimeError("finalize roto")

	monkeypatch.setattr("red_pill.metabolism.sleep.finalize_sleep_cycle", _boom)

	m = SleepFinalizeMinion()
	res = _run(m.execute(""))
	assert res["status"] == "failed"
	assert "finalize roto" in res["error"]


# ── _read_total_processed ─────────────────────────────────────────────────────

def test_read_total_processed_sin_fichero(monkeypatch, tmp_path):
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: tmp_path)
	from red_pill.swarm.agents.sleep_minions import _read_total_processed

	assert _read_total_processed() == 0


def test_read_total_processed_con_fichero(monkeypatch, tmp_path):
	(tmp_path / "sleep_phase_status.json").write_text(json.dumps({"total_processed": 88}), encoding="utf-8")
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: tmp_path)
	from red_pill.swarm.agents.sleep_minions import _read_total_processed

	assert _read_total_processed() == 88


def test_read_total_processed_fichero_invalido(monkeypatch, tmp_path):
	(tmp_path / "sleep_phase_status.json").write_text("no-json", encoding="utf-8")
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: tmp_path)
	from red_pill.swarm.agents.sleep_minions import _read_total_processed

	assert _read_total_processed() == 0
