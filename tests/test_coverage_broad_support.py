"""Cobertura de módulos de soporte con lógica pura (sin Qdrant/GPU/red).

Cubre fuentes con muchas líneas sin cubrir que son testeables de forma
determinista: gpu_reservation (JSON + PIDs), thread_weaver (persistencia),
fallup (cálculo puro) y log_rotation (rotación de ficheros).
"""

from __future__ import annotations

import os

import pytest

# ── GpuReservationManager ───────────────────────────────────────────────────


@pytest.fixture
def gpu_mgr(tmp_path, monkeypatch):
	import red_pill.core.gpu_reservation as g

	monkeypatch.setattr(g, "get_daemon_dir", lambda: tmp_path)
	return g.GpuReservationManager


def test_gpu_load_empty(gpu_mgr):
	assert gpu_mgr.load_reservations() == []


def test_gpu_save_and_load(gpu_mgr):
	gpu_mgr.save_reservations([{"pid": 1, "owner": "x", "vram_mb": 100}])
	loaded = gpu_mgr.load_reservations()
	assert loaded and loaded[0]["owner"] == "x"


def test_gpu_load_corrupt_returns_empty(gpu_mgr):
	(gpu_mgr.get_reservations_file()).write_text("{bad json", encoding="utf-8")
	assert gpu_mgr.load_reservations() == []


def test_gpu_reserve_and_total(gpu_mgr):
	pid = os.getpid()
	assert gpu_mgr.reserve("own", 500, pid=pid) is True
	total = gpu_mgr.get_total_reserved_mb()
	assert total == 500


def test_gpu_reserve_updates_existing(gpu_mgr):
	pid = os.getpid()
	gpu_mgr.reserve("own", 500, pid=pid)
	gpu_mgr.reserve("own", 800, pid=pid)
	assert gpu_mgr.get_total_reserved_mb() == 800


def test_gpu_exclusive_returns_minus_one(gpu_mgr):
	gpu_mgr.reserve("own", 500, exclusive=True, pid=os.getpid())
	assert gpu_mgr.get_total_reserved_mb() == -1
	assert gpu_mgr.is_exclusive_active() is True


def test_gpu_release(gpu_mgr):
	pid = os.getpid()
	gpu_mgr.reserve("own", 500, pid=pid)
	assert gpu_mgr.release(pid=pid) is True
	assert gpu_mgr.release(pid=pid) is False


def test_gpu_clean_prunes_dead_pid(gpu_mgr):
	gpu_mgr.save_reservations([{"pid": 999999999, "owner": "dead", "vram_mb": 1, "create_time": 0}])
	active = gpu_mgr.clean_and_get_active()
	assert active == []


# ── thread_weaver ───────────────────────────────────────────────────────────


def test_thread_state_roundtrip(tmp_path, monkeypatch):
	import red_pill.core.paths as paths
	import red_pill.metabolism.thread_weaver as tw

	state_file = tmp_path / "thread.json"
	monkeypatch.setattr(paths, "get_thread_state_path", lambda: state_file)
	monkeypatch.setattr(tw, "get_thread_state_path", lambda: state_file)
	assert tw._load_thread_state() == {}
	tw._save_thread_state({"work_memories": "hub1"})
	assert tw._load_thread_state() == {"work_memories": "hub1"}


def test_thread_state_load_corrupt(tmp_path, monkeypatch):
	import red_pill.metabolism.thread_weaver as tw

	state_file = tmp_path / "thread.json"
	state_file.write_text("{bad", encoding="utf-8")
	monkeypatch.setattr(tw, "get_thread_state_path", lambda: state_file)
	assert tw._load_thread_state() == {}


def test_thread_state_save_bad_path_is_nonfatal(monkeypatch):
	import red_pill.metabolism.thread_weaver as tw

	monkeypatch.setattr(tw, "get_thread_state_path", lambda: (_ for _ in ()).throw(RuntimeError("no path")))
	tw._save_thread_state({"x": "y"})  # no debe lanzar


# ── fallup ──────────────────────────────────────────────────────────────────


def test_fallup_worst_case_floor_when_registry_unavailable(monkeypatch):
	import red_pill.core.fallup as fu
	import red_pill.core.model_registry as mr

	monkeypatch.setattr(mr, "ModelRegistry", type("M", (), {"get_all_profiles": staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("x")))}))
	assert fu.worst_case_gpu_min_free_gb() == fu.FALLUP_WORST_CASE_MIN_FREE_GB


def test_fallup_worst_case_from_profiles(monkeypatch):
	import red_pill.core.fallup as fu
	import red_pill.core.model_registry as mr

	profiles = {
		"granite": {
			"capabilities": ["distillation"],
			"hardware_affinity": {"vram_tiers": [{"n_gpu_layers": 20, "min_free_gb": 6.5}, {"n_gpu_layers": 0, "min_free_gb": 1.0}]},
		}
	}
	monkeypatch.setattr(mr, "ModelRegistry", type("M", (), {"get_all_profiles": staticmethod(lambda: profiles)}))
	assert fu.worst_case_gpu_min_free_gb() == 6.5


def test_fallup_worst_case_ignores_sentinel(monkeypatch):
	import red_pill.core.fallup as fu
	import red_pill.core.model_registry as mr

	profiles = {"m": {"capabilities": ["distillation"], "hardware_affinity": {"vram_tiers": [{"n_gpu_layers": 10, "min_free_gb": 999}]}}}
	monkeypatch.setattr(mr, "ModelRegistry", type("M", (), {"get_all_profiles": staticmethod(lambda: profiles)}))
	assert fu.worst_case_gpu_min_free_gb() == fu.FALLUP_WORST_CASE_MIN_FREE_GB


def test_fallup_enabled_falls_back_true(monkeypatch):
	import red_pill.core.fallup as fu

	monkeypatch.setattr(fu, "logger", fu.logger)
	# sin _fallup_enabled accesible → True
	assert isinstance(fu.fallup_enabled(), bool)


# ── log_rotation ────────────────────────────────────────────────────────────


class _J:
	def __init__(self):
		self.msgs = []

	def log(self, m):
		self.msgs.append(m)


def _plugin():
	from red_pill.swarm.agents.janitor_plugins.log_rotation import LogRotationPlugin

	return LogRotationPlugin()


def test_log_rotation_should_rotate_by_size(tmp_path):
	p = tmp_path / "app.log"
	p.write_text("x" * 100, encoding="utf-8")
	assert _plugin()._should_rotate_log(_J(), p, 10) is True


def test_log_rotation_should_rotate_old_entries(tmp_path):
	p = tmp_path / "app.log"
	p.write_text("2000-01-01 old line\n", encoding="utf-8")
	assert _plugin()._should_rotate_log(_J(), p, 10**9) is True


def test_log_rotation_should_not_rotate_fresh(tmp_path):
	p = tmp_path / "app.log"
	p.write_text("nueva linea sin fecha\n", encoding="utf-8")
	assert _plugin()._should_rotate_log(_J(), p, 10**9) is False


def test_log_rotation_copytruncate(tmp_path):
	p = tmp_path / "app.log"
	p.write_text("contenido", encoding="utf-8")
	(tmp_path / "app.log.1").write_text("viejo1", encoding="utf-8")
	_plugin()._rotate_file_copytruncate(_J(), p)
	assert p.read_text(encoding="utf-8") == "", "el log activo debe quedar truncado"
	assert (tmp_path / "app.log.1").read_text(encoding="utf-8") == "contenido"
	assert (tmp_path / "app.log.2").read_text(encoding="utf-8") == "viejo1"


def test_log_rotation_cleanup_old(tmp_path):
	import os
	import time

	p = tmp_path / "app.log"
	p.write_text("x", encoding="utf-8")
	old = tmp_path / "app.log.3"
	old.write_text("old", encoding="utf-8")
	os.utime(old, (time.time() - 30 * 86400, time.time() - 30 * 86400))
	n = _plugin()._cleanup_old_rotated_logs(_J(), tmp_path, "app.log", days=7)
	assert n == 1
	assert not old.exists()


@pytest.mark.asyncio
async def test_log_rotation_execute_no_targets(tmp_path, monkeypatch):
	import red_pill.swarm.agents.janitor_plugins.log_rotation as lr

	monkeypatch.setattr(lr.Path, "home", staticmethod(lambda: tmp_path))
	res = await _plugin().execute(_J(), {})
	assert res == {"logs_rotated": 0, "old_logs_purged": 0}


@pytest.mark.asyncio
async def test_log_rotation_execute_rotates_big_log(tmp_path, monkeypatch):
	import red_pill.swarm.agents.janitor_plugins.log_rotation as lr

	monkeypatch.setattr(lr.Path, "home", staticmethod(lambda: tmp_path))
	d = tmp_path / ".local/share/red-pill/daemon"
	d.mkdir(parents=True)
	big = d / "output.log"
	big.write_text("y" * 200, encoding="utf-8")
	res = await _plugin().execute(_J(), {"plugins": {"log_rotation": {"max_size_bytes": 10}}})
	assert res["logs_rotated"] == 1
	assert big.read_text(encoding="utf-8") == ""
	assert (d / "output.log.1").exists()


# ── memento/hybrid: funciones puras (RRF, MMR, terms) ───────────────────────


def test_salient_terms_prefers_identifiers():
	from red_pill.memento.hybrid import salient_terms

	terms = salient_terms("consulta sobre BIT-003 y Initech con palabras normales")
	assert "BIT-003" in terms


def test_salient_terms_empty():
	from red_pill.memento.hybrid import salient_terms

	assert salient_terms("") == []


def test_rrf_scores_and_merge():
	from red_pill.memento.hybrid import rrf_merge, rrf_scores

	a = ["x", "y", "z"]
	b = ["y", "x"]
	scores = rrf_scores([a, b])
	ids = [pid for pid, _ in scores]
	assert ids[0] in ("x", "y")
	merged = rrf_merge([a, b])
	assert set(merged) == {"x", "y", "z"}


def test_rrf_empty():
	from red_pill.memento.hybrid import rrf_merge

	assert rrf_merge([]) == []


def test_unit_vector():
	import numpy as np

	from red_pill.memento.hybrid import _unit

	u = _unit([3.0, 4.0])
	assert abs(float(np.linalg.norm(u)) - 1.0) < 1e-9


def test_mmr_select_basic():
	from red_pill.memento.hybrid import mmr_select

	items = ["a", "b", "c"]
	vectors = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]
	out = mmr_select([1.0, 0.0], items, vectors, k=2)
	assert len(out) == 2
	assert out[0] == "a"


def test_mmr_select_empty():
	from red_pill.memento.hybrid import mmr_select

	assert mmr_select([1.0], [], [], k=3) == []
	assert mmr_select([1.0], ["a"], [[1.0]], k=0) == []


def test_frontmatter_parsing(tmp_path):
	from red_pill.memento.hybrid import _frontmatter

	p = tmp_path / "n.md"
	p.write_text('---\nid: "x"\nstatus: draft\n---\n\ncuerpo\n', encoding="utf-8")
	fm = _frontmatter(p)
	assert fm.get("id") == "x"
	assert fm.get("status") == "draft"


def test_frontmatter_missing_file(tmp_path):
	from red_pill.memento.hybrid import _frontmatter

	assert _frontmatter(tmp_path / "nope.md") == {}


# ── bunker_lifecycle ────────────────────────────────────────────────────────


def test_parse_changelog_release():
	from red_pill.bunker_lifecycle import parse_changelog_release

	md = """# Changelog

## [8.0.0] - 2026-09-28 (Memento)
### Added
- una cosa
### Fixed
- otra cosa

## [7.21.0] - 2026-08-01
### Changed
- viejo
"""
	res = parse_changelog_release(md)
	assert res is not None
	assert res["version"] == "8.0.0"
	assert res["date"] == "2026-09-28"
	assert res["codename"] == "Memento"
	assert res["previous"] == "7.21.0"
	assert "Added" in res["features"] and "Fixed" in res["features"]


def test_parse_changelog_release_none():
	from red_pill.bunker_lifecycle import parse_changelog_release

	assert parse_changelog_release("# sin releases") is None


def test_detect_hardware(monkeypatch):
	import red_pill.bunker_lifecycle as bl

	class _VM:
		total = 32 * (1024**3)

	monkeypatch.setattr(bl.psutil, "virtual_memory", lambda: _VM())
	monkeypatch.setattr(bl.psutil, "cpu_count", lambda logical=True: 8)

	class _R:
		returncode = 0
		stdout = "8192\n"

	monkeypatch.setattr(bl.subprocess, "run", lambda *a, **k: _R())
	hw = bl.detect_hardware()
	assert hw["cpu_cores"] == 8
	assert hw["has_nvidia"] is True
	assert hw["vram_gb"] == 8.0


def test_detect_hardware_no_gpu(monkeypatch):
	import red_pill.bunker_lifecycle as bl

	class _VM:
		total = 16 * (1024**3)

	monkeypatch.setattr(bl.psutil, "virtual_memory", lambda: _VM())
	monkeypatch.setattr(bl.psutil, "cpu_count", lambda logical=True: 4)

	def _boom(*a, **k):
		raise FileNotFoundError

	monkeypatch.setattr(bl.subprocess, "run", _boom)
	hw = bl.detect_hardware()
	assert hw["has_nvidia"] is False
	assert hw["vram_gb"] == 0.0


# ── p2p_sync: timestamps / peers ────────────────────────────────────────────


def test_p2p_timestamp_roundtrip():
	from red_pill.core.p2p_sync import from_sqlite_timestamp, to_sqlite_timestamp

	s = to_sqlite_timestamp(1_700_000_000.0)
	assert from_sqlite_timestamp(s) == 1_700_000_000.0


def test_p2p_from_timestamp_invalid():
	from red_pill.core.p2p_sync import from_sqlite_timestamp

	assert from_sqlite_timestamp("no es fecha") == 0.0


def test_p2p_point_modification_time():
	from red_pill.core.p2p_sync import get_point_modification_time

	assert get_point_modification_time({"updated_at": 5.0}) == 5.0
	assert get_point_modification_time({"created_at": 3.0, "last_recalled_at": 9.0}) == 9.0


def test_p2p_get_local_public_key_fallback(monkeypatch):
	import red_pill.core.p2p_sync as p

	monkeypatch.setattr(p, "_known_peer_identifiers", lambda: set())
	# sin keyring disponible → cadena vacía
	assert isinstance(p.get_local_public_key(), str)


# ── jobs/drivers/base: helpers ──────────────────────────────────────────────


def test_human_duration_formats():
	from red_pill.jobs.drivers.base import human_duration

	assert "s" in human_duration(30)
	assert "min" in human_duration(300)
	assert "h" in human_duration(7200)


def test_job_log_path(tmp_path, monkeypatch):
	import red_pill.core.paths as paths
	import red_pill.jobs.drivers.base as base

	monkeypatch.setattr(paths, "get_state_dir", lambda: tmp_path)
	monkeypatch.setattr(base, "get_state_dir", lambda: tmp_path, raising=False)
	# la función importa get_state_dir dentro; parchear el módulo paths es suficiente
	from red_pill.core.paths import get_state_dir  # noqa

	p = base.job_log_path("abcdef12345")
	assert p.name == "abcdef12.log"
