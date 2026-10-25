"""B-01h — write-ahead de turnos en arneses externos."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import red_pill.session.external_turns as ext
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry

CID = "01a1728b-8cc4-7cf8-a9e2-f110b1b5857d"


@pytest.fixture
def state(tmp_path, monkeypatch):
	root = tmp_path / "red-pill" / "state"
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
	monkeypatch.setattr(ext, "get_state_dir", lambda: root)
	return root


@pytest.fixture
def db(tmp_path):
	path = tmp_path / "session.db"
	return path, SessionRegistry(str(path)), SessionMirror(str(path))


def _hook_module(monkeypatch, name, filename):
	path = Path(__file__).resolve().parents[1] / "seeds" / "settings" / "hooks" / filename
	spec = importlib.util.spec_from_file_location(name, path)
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def test_journal_roundtrip_and_supersede(state):
	first = ext.begin_external_turn(provider="opencode", session_id="s1", prompt="uno")
	second = ext.begin_external_turn(provider="opencode", session_id="s1", prompt="dos")
	assert second["request_id"] != first["request_id"]
	archive = state / ext.ARCHIVE_DIR / f"opencode__s1__{ext._safe(first['request_id'])}.json"
	assert archive.is_file()
	data = json.loads(archive.read_text())
	assert data["status"] == "aborted" and data["reason"] == "superseded"


def test_import_completed_turn_into_mirror(state, db):
	path, registry, mirror = db
	registry.upsert_session(originator="opencode:s1", continuity_id=CID, mission_id="repo:next", role="task")
	turn = ext.begin_external_turn(provider="opencode", session_id="s1", prompt="hola")
	ext.finish_external_turn(provider="opencode", session_id="s1", response="mundo", model="m")
	counts = ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	assert counts["completed"] == 1
	rows = mirror.pending_turns(CID, include_aborted=True)
	assert rows == []
	# El archivo cerrado se consume; el espejo conserva user+assistant.
	archives = list((state / ext.ARCHIVE_DIR).glob("*.json"))
	assert archives == []
	con = __import__("sqlite3").connect(path)
	statuses = con.execute("SELECT status FROM session_mirror WHERE request_id=?", (turn["request_id"],)).fetchall()
	con.close()
	assert statuses == [("completed",), ("completed",)]


def test_unregistered_originator_is_not_invented(state, db):
	_, registry, mirror = db
	ext.begin_external_turn(provider="opencode", session_id="ghost", prompt="hola")
	counts = ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	assert counts["skipped"] == 1
	assert list((state / ext.CURRENT_DIR).glob("*.json"))


def test_aborted_turn_keeps_partial_response(state, db):
	_, registry, mirror = db
	registry.upsert_session(originator="pi:s1", continuity_id=CID, mission_id="repo:next", role="task")
	turn = ext.begin_external_turn(provider="pi", session_id="s1", prompt="hola")
	ext.finish_external_turn(provider="pi", session_id="s1", status="aborted", response="a medias", reason="timeout")
	ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	rows = mirror.pending_turns(CID, include_aborted=True)
	assert any(r["request_id"] == turn["request_id"] and r["status"] == "aborted" for r in rows)
	assert any("a medias" in str(r.get("content")) for r in rows)


def test_claude_hooks_write_same_journal(state, monkeypatch, db):
	_, registry, mirror = db
	registry.upsert_session(originator="claude_code:s1", continuity_id=CID, mission_id="repo:next", role="task")
	start = _hook_module(monkeypatch, "b01h_turn_start", "redpill_turn_start.py")
	scribe = _hook_module(monkeypatch, "b01h_scribe", "redpill_scribe.py")
	start._begin_turn({"prompt": "hola", "cwd": "/tmp"}, "s1")
	scribe._finish_turn("s1", "mundo", "claude-x", "completed")
	counts = ext.import_external_turns(mirror=mirror, registry=registry, root=state)
	assert counts["completed"] == 1
