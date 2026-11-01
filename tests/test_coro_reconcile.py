"""Reconciliador `mission_events -> outbox` (S2.2)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time

import pytest

from red_pill.coro import mailbox
from red_pill.session import delivery
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
	return reg, session_db, events_db


def _event(reg, *, verb="notify", summary="hola", expires_at=None):
	return reg.add_event(
		event_type="message",
		mission_id="repo:test",
		summary=summary,
		continuity_id="soul-1",
		originator="opencode:ses_a",
		global_turn=1,
		to_continuity="soul-1",
		verb=verb,
		thread_id="E-test",
		expires_at=expires_at,
	)


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


def test_reconcile_publica_solo_lo_que_falta(db):
	reg, _, events_db = db
	ok = _event(reg, summary="publicar")
	with_receipt = _event(reg, summary="ya leído")
	delivery.set_receipt(event_id=with_receipt["event_id"], continuity_id="soul-1", state=delivery.STATE_READ, db_path=reg.db_path)
	_event(reg, verb="park", summary="park no se publica")
	_event(reg, summary="expirado", expires_at=time.time() - 10)

	report = mailbox.reconcile(hours=0, since_seq=0)
	assert report["scanned"] == 1
	assert report["published"] == 1
	rows = _outbox(events_db)
	assert len(rows) == 1
	assert rows[0]["message_id"] == ok["event_id"]
	assert rows[0]["channel"] == "soul"
	assert "publicar" not in rows[0]["payload"]


def test_reconcile_es_idempotente(db):
	reg, _, events_db = db
	_event(reg)
	mailbox.reconcile(hours=0, since_seq=0)
	mailbox.reconcile(hours=0)
	assert len(_outbox(events_db)) == 1


def test_primera_pasada_es_baseline_y_no_publica(db):
	reg, _, events_db = db
	_event(reg)
	report = mailbox.reconcile()
	assert report["baseline"] is True
	assert report["scanned"] == 0
	assert _outbox(events_db) == []
	assert mailbox.reconcile()["scanned"] == 0


def test_dry_run_no_publica(db):
	reg, _, events_db = db
	_event(reg)
	report = mailbox.reconcile(hours=0, dry_run=True, since_seq=0)
	assert report["scanned"] == 1
	assert report["published"] == 0
	assert _outbox(events_db) == []


def test_cli_coro_reconcile_json(db, capsys):
	reg, _, events_db = db
	_event(reg)
	from red_pill.cli_services import handle_coro

	handle_coro(argparse.Namespace(coro_cmd="reconcile", limit=200, hours=0.0, dry_run=False, json=True, since_seq=0))
	out = json.loads(capsys.readouterr().out)
	assert out["published"] == 1
	assert len(_outbox(events_db)) == 1
