"""B-01L Fase 1 — schema y API de leases (work + mission)."""

from __future__ import annotations

import sqlite3

import pytest

from red_pill.session.lease import LeaseError, LeaseHeld, LeaseStore
from red_pill.session.store import SessionRegistry


@pytest.fixture
def leases(tmp_path):
	db = str(tmp_path / "session.db")
	SessionRegistry(db)
	return LeaseStore(db)


def test_schema_v7_has_session_leases(tmp_path):
	"""v7 trajo los leases; v8 (AD-095) añadió la correspondencia del coro."""
	path = tmp_path / "session.db"
	SessionRegistry(str(path))
	con = sqlite3.connect(path)
	assert con.execute("PRAGMA user_version").fetchone()[0] == 8
	cols = {r[1] for r in con.execute("PRAGMA table_info(session_leases)")}
	assert {"lease_key", "scope", "subject_id", "continuity_id", "state", "idle_ttl_s", "max_wall_s"} <= cols
	assert con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_leases_heartbeat'").fetchone()
	con.close()


def test_work_lease_roundtrip(leases):
	row = leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="repo:next", owner_kind="bridge")
	assert row["state"] == "active" and row["scope"] == "work"
	assert leases.get("req-1")["subject_id"] == "req-1"
	beat = leases.heartbeat("req-1")
	assert beat["last_heartbeat_at"] >= row["last_heartbeat_at"]
	done = leases.finish("req-1", state="completed")
	assert done["state"] == "completed"


def test_same_owner_is_idempotent_other_owner_blocked(leases):
	first = leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m")
	again = leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m")
	assert again["lease_key"] == first["lease_key"]
	with pytest.raises(LeaseHeld):
		leases.begin_work_lease("req-1", continuity_id="alma-2", mission_id="m")


def test_expired_lease_requires_force_to_change_soul(leases):
	import time

	leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m", idle_ttl_s=1, max_wall_s=10)
	time.sleep(1.05)
	with pytest.raises(LeaseHeld):
		leases.begin_work_lease("req-1", continuity_id="alma-2", mission_id="m", idle_ttl_s=1, max_wall_s=10)
	row = leases.begin_work_lease(
		"req-1", continuity_id="alma-2", mission_id="m", idle_ttl_s=1, max_wall_s=10, allow_takeover=True
	)
	assert row["continuity_id"] == "alma-2"


def test_mission_lease_uses_same_table(leases):
	row = leases.begin_mission_lease("repo:next", continuity_id="alma-1", holder_originator="opencode:s1")
	assert row["scope"] == "mission" and row["lease_key"] == "mission:repo:next"
	assert leases.active_mission_lease("repo:next")["continuity_id"] == "alma-1"
	assert leases.active_mission_lease("repo:other") is None


def test_heartbeat_keeps_alive_and_sweep_marks_stalled(leases):
	leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m", idle_ttl_s=100, max_wall_s=1000)
	leases.heartbeat("req-1")
	assert leases.sweep(now=leases.get("req-1")["last_heartbeat_at"] + 50) == []
	expired = leases.sweep(now=leases.get("req-1")["last_heartbeat_at"] + 101)
	assert expired[0]["expired_reason"] == "idle_ttl"
	assert leases.get("req-1")["state"] == "stalled"


def test_max_wall_cannot_be_exceeded_by_extension(leases):
	leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m", idle_ttl_s=100, max_wall_s=100)
	row = leases.extend_lease("req-1", seconds=100, reason="compilación", max_ceiling_s=150)
	assert row["max_wall_s"] == 150
	row = leases.extend_lease("req-1", seconds=100, reason="compilación")
	assert row["max_wall_s"] == 250
	with pytest.raises(ValueError):
		leases.extend_lease("req-1", seconds=1, reason="")


def test_owner_is_enforced_on_heartbeat_and_finish(leases):
	leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m")
	with pytest.raises(LeaseHeld):
		leases.heartbeat("req-1", continuity_id="alma-2")
	with pytest.raises(LeaseHeld):
		leases.finish("req-1", continuity_id="alma-2")


def test_completed_lease_cannot_be_downgraded(leases):
	leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m")
	leases.finish("req-1", state="completed")
	with pytest.raises(LeaseError):
		leases.finish("req-1", state="stalled")


def test_heartbeat_marks_stalled_after_max_wall(leases, monkeypatch):
	import red_pill.session.lease as lease_mod

	clock = [1000.0]
	monkeypatch.setattr(lease_mod, "_now", lambda: clock[0])
	leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m", max_wall_s=10)
	clock[0] = 1011.0
	row = leases.heartbeat("req-1")
	assert row["state"] == "stalled" and row["reason"] == "max_wall"


def test_unknown_lease_is_explicit(leases):
	with pytest.raises(LeaseError):
		leases.heartbeat("nope")
	with pytest.raises(LeaseError):
		leases.finish("nope")


def test_active_lease_requires_force_to_change_soul(leases):
	leases.begin_work_lease("req-1", continuity_id="alma-1", mission_id="m")
	with pytest.raises(LeaseHeld):
		leases.begin_work_lease("req-1", continuity_id="alma-2", mission_id="m")
	row = leases.begin_work_lease("req-1", continuity_id="alma-2", mission_id="m", allow_takeover=True)
	assert row["continuity_id"] == "alma-2"
