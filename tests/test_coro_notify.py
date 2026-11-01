"""Avisos de job/CI/minion por el coro (S2.1+)."""

from __future__ import annotations

import json
import sqlite3

import pytest

from red_pill.coro import notify
from red_pill.session.store import SessionRegistry


@pytest.fixture
def db(tmp_path, monkeypatch):
	session_db = tmp_path / "session.db"
	events_db = tmp_path / "events.db"
	monkeypatch.setattr("red_pill.session.store.get_session_db", lambda: str(session_db))
	monkeypatch.setattr("red_pill.core.paths.get_session_db", lambda: str(session_db))
	monkeypatch.setattr("red_pill.core.paths.get_neon_link_db_path", lambda: events_db)
	reg = SessionRegistry(str(session_db))
	reg.upsert_session(originator="opencode:ses_a", continuity_id="soul-1", mission_id="repo:test")
	return session_db, events_db


def _events(session_db):
	con = sqlite3.connect(str(session_db))
	con.row_factory = sqlite3.Row
	try:
		return [dict(r) for r in con.execute("SELECT * FROM mission_events ORDER BY event_seq")]
	finally:
		con.close()


def _outbox(events_db):
	if not events_db.exists():
		return []
	con = sqlite3.connect(str(events_db))
	con.row_factory = sqlite3.Row
	try:
		return [dict(r) for r in con.execute("SELECT * FROM outbox ORDER BY id")]
	except sqlite3.OperationalError:
		return []
	finally:
		con.close()


def test_publish_notice_escribe_evento_y_sobre(db):
	session_db, events_db = db
	assert notify.publish_notice(
		continuity_id="soul-1",
		body="[JOB] terminó el CI",
		originator="job:abc",
	) is True
	events = _events(session_db)
	assert len(events) == 1
	assert events[0]["to_continuity"] == "soul-1"
	assert events[0]["continuity_id"] == "soul-1"
	assert events[0]["originator"] == "job:abc"
	assert events[0]["verb"] == "notify"
	assert events[0]["mission_id"] == "repo:test"
	outbox = _outbox(events_db)
	assert len(outbox) == 1
	payload = json.loads(outbox[0]["payload"])
	assert payload["event_id"] == events[0]["event_id"]
	assert "summary" not in payload
	assert "terminó el CI" not in outbox[0]["payload"]


def test_publish_notice_resuelve_mision_del_registro(db):
	session_db, _ = db
	assert notify.publish_notice(continuity_id="soul-1", body="hola", originator="job:x") is True
	assert _events(session_db)[0]["mission_id"] == "repo:test"


def test_publish_notice_sin_mision_ni_registro_falla(db):
	session_db, events_db = db
	assert notify.publish_notice(continuity_id="soul-2", body="hola", originator="job:x") is False
	assert _events(session_db) == []
	assert _outbox(events_db) == []


def test_publish_notice_sin_cuerpo_falla(db):
	_, events_db = db
	assert notify.publish_notice(continuity_id="soul-1", body="") is False
	assert _outbox(events_db) == []
