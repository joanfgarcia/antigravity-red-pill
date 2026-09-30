import time

from red_pill.core import session_index as si
from red_pill.core.session_liveness import SessionSignal


def test_board_line_silent_with_one(monkeypatch):
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("opencode", "a", now, None)])
	assert si.board_line() == ""


def test_board_line_with_others(monkeypatch):
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(
		si,
		"list_sessions",
		lambda: [SessionSignal("opencode", "a", now, None), SessionSignal("claude_code", "b", now, None)],
	)
	assert si.board_line().startswith("[BOARD: 2 sesiones vivas]")


def test_build_board_enriched(monkeypatch):
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("opencode", "ses_x", now - 1, None)])
	monkeypatch.setattr(si, "_opencode_meta", lambda sid: {"directory": "/home/joan/Documents/IA/sharing", "title": "T", "model": "m"})
	monkeypatch.setattr(si, "_origin_for", lambda p, s: "awakening")
	monkeypatch.setattr(si, "_owning_workspace", lambda d: "sharing")

	board = si.build_board()
	assert len(board) == 1
	b = board[0]
	assert b["provider"] == "opencode"
	assert b["origin"] == "awakening"
	assert b["project"] == "sharing"
	assert b["title"] == "T"
	assert b["model"] == "m"
	assert b["in_flight"] is True
	assert b["active"] is True


def test_build_board_non_opencode_has_no_meta(monkeypatch):
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("claude_code", "uuid-1", now - 2, now - 1)])
	called = {"n": 0}

	def _meta(sid):
		called["n"] += 1
		return {}

	monkeypatch.setattr(si, "_opencode_meta", _meta)
	board = si.build_board()
	assert board[0]["provider"] == "claude_code"
	assert board[0]["directory"] is None
	assert called["n"] == 0  # no se consulta la DB de opencode para otros providers
