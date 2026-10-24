"""B-01s: turn write-ahead y estado de turno en el espejo del alma."""

import time

import pytest

from red_pill.mini.session import MiniConfig, MiniSession
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry


class _Provider:
	def __init__(self, response=None, error=None):
		self.response = response
		self.error = error
		self.calls = 0

	def chat(self, messages, **kwargs):
		self.calls += 1
		if self.error:
			raise RuntimeError(self.error)
		return {"role": "assistant", "content": self.response}


def _mirror(tmp_path):
	return SessionMirror(str(tmp_path / "session.db"))


def test_begin_complete_and_read_only_completed(tmp_path):
	mirror = _mirror(tmp_path)
	mirror.begin_turn(
		continuity_id="alma-b01s",
		mission_id="mission:b01s",
		request_id="turn-1",
		content="hola",
		originator="sip:s1",
		source="sip",
	)
	assert mirror.read_turns("alma-b01s") == []
	pending = mirror.pending_turns("alma-b01s", include_aborted=False)
	assert len(pending) == 1 and pending[0]["status"] == "pending"
	assert pending[0]["request_id"] == "turn-1"

	mirror.complete_turn(continuity_id="alma-b01s", request_id="turn-1")
	turns = mirror.read_turns("alma-b01s")
	assert [t["role"] for t in turns] == ["user"]
	assert turns[0]["status"] == "completed"
	assert mirror.pending_turns("alma-b01s", include_aborted=False) == []


def test_begin_is_idempotent_by_source_ref(tmp_path):
	mirror = _mirror(tmp_path)
	args = dict(
		continuity_id="alma-b01s",
		mission_id="mission:b01s",
		request_id="turn-1",
		content="hola",
		originator="sip:s1",
		source="sip",
	)
	first = mirror.begin_turn(**args)
	second = mirror.begin_turn(**args)
	assert first["seq"] == second["seq"]
	assert len(mirror.pending_turns("alma-b01s")) == 1


def test_abort_with_partial_keeps_evidence_out_of_replay(tmp_path):
	mirror = _mirror(tmp_path)
	mirror.begin_turn(
		continuity_id="alma-b01s",
		mission_id="mission:b01s",
		request_id="turn-2",
		content="hola",
		originator="sip:s1",
		source="sip",
	)
	mirror.abort_turn(
		continuity_id="alma-b01s",
		request_id="turn-2",
		reason="provider_error",
		partial_response="respuesta parcial",
		mission_id="mission:b01s",
	)
	assert mirror.read_turns("alma-b01s") == []
	aborted = mirror.read_turns("alma-b01s", statuses=["aborted"])
	assert [t["role"] for t in aborted] == ["user", "assistant"]
	assert all(t["status"] == "aborted" for t in aborted)
	assert aborted[-1]["content"] == "respuesta parcial"


def test_expire_pending_marks_ttl_without_deleting(tmp_path):
	mirror = _mirror(tmp_path)
	mirror.begin_turn(
		continuity_id="alma-b01s",
		mission_id="mission:b01s",
		request_id="old",
		content="hola",
		originator="sip:s1",
		source="sip",
		ts=time.time() - 3600,
	)
	assert mirror.expire_pending_turns(max_age_s=60, continuity_id="alma-b01s") == 1
	rows = mirror.read_turns("alma-b01s", statuses=["aborted"])
	assert len(rows) == 1 and rows[0]["status_reason"] == "ttl"


def test_schema_v5_has_status_columns(tmp_path):
	db = tmp_path / "session.db"
	SessionRegistry(str(db))
	import sqlite3

	with sqlite3.connect(db) as conn:
		cols = {row[1] for row in conn.execute("PRAGMA table_info(session_mirror)").fetchall()}
		version = conn.execute("PRAGMA user_version").fetchone()[0]
	assert {"status", "request_id", "status_reason"} <= cols
	assert version >= 5


def _mini(tmp_path, provider):
	workspace = tmp_path / "ws"
	workspace.mkdir()
	return MiniSession(
		MiniConfig(
			workspace=str(workspace),
			continuity_id="alma-b01s-mini",
			mission_id="mission:b01s",
			db_path=str(tmp_path / "session.db"),
		),
		{"forge": provider},
	)


def test_mini_session_success_completes_group(tmp_path):
	provider = _Provider(response="ok")
	session = _mini(tmp_path, provider)
	result = session.run("forge", system_prompt="sys", task="hola")
	assert result["request_id"]
	assert provider.calls == 1
	turns = session.mirror.read_turns("alma-b01s-mini")
	assert [t["role"] for t in turns] == ["user", "assistant"]
	assert all(t["status"] == "completed" for t in turns)
	assert session.mirror.pending_turns("alma-b01s-mini", include_aborted=False) == []


def test_mini_session_provider_error_aborts_group(tmp_path):
	provider = _Provider(error="boom")
	session = _mini(tmp_path, provider)
	with pytest.raises(RuntimeError, match="boom"):
		session.run("forge", system_prompt="sys", task="hola")
	assert session.mirror.read_turns("alma-b01s-mini") == []
	rows = session.mirror.read_turns("alma-b01s-mini", statuses=["aborted"])
	assert len(rows) == 1 and rows[0]["status_reason"].startswith("provider_error")


def test_cli_pending_and_resume(capsys):
	import json
	from types import SimpleNamespace

	from red_pill.cli_services import handle_session

	mirror = SessionMirror()
	mirror.begin_turn(
		continuity_id="cli-alma",
		mission_id="mission:cli",
		request_id="cli-1",
		content="prompt pendiente",
		originator="sip:cli",
		source="sip",
	)
	handle_session(SimpleNamespace(session_cmd="pending", continuity="cli-alma", json=True, expire=False, max_age_min=None))
	rows = json.loads(capsys.readouterr().out)
	assert rows[0]["request_id"] == "cli-1"
	assert rows[0]["status"] == "pending"

	handle_session(SimpleNamespace(session_cmd="resume", request_id="cli-1", continuity="cli-alma", json=False))
	out = capsys.readouterr().out
	assert "prompt pendiente" in out
	assert "cli-1" in out
