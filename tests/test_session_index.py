import sqlite3
import time

import pytest

from red_pill.core import session_index as si
from red_pill.core.session_liveness import SessionSignal


@pytest.fixture(autouse=True)
def _isolated_opencode_db(tmp_path, monkeypatch):
	"""Nunca leer el `opencode.db` real del operador: por defecto, una ruta inexistente."""
	monkeypatch.setattr(si, "_opencode_db_path", lambda: tmp_path / "no-opencode.db")


def _opencode_db(path, rows):
	"""`opencode.db` mínimo: tabla `session` con las columnas que lee el tablón."""
	con = sqlite3.connect(path)
	con.execute("CREATE TABLE session (id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT NOT NULL, title TEXT NOT NULL, model TEXT)")
	con.executemany("INSERT INTO session (id, parent_id, directory, title, model) VALUES (?, ?, ?, ?, ?)", rows)
	con.commit()
	con.close()
	return path


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


def test_subsessions_excluded_from_board_and_line(tmp_path, monkeypatch):
	"""Las sub-sesiones opencode (`parent_id` no nulo) no cuentan como sesiones vivas."""
	now = time.time()
	db = _opencode_db(
		tmp_path / "opencode.db",
		[
			("ses_parent", None, "/w", "Padre", None),
			("ses_child1", "ses_parent", "/w", "Panel 1", None),
			("ses_child2", "ses_parent", "/w", "Panel 2", None),
		],
	)
	monkeypatch.setattr(si, "_opencode_db_path", lambda: db)
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "_origin_for", lambda p, s: None)
	monkeypatch.setattr(si, "_owning_workspace", lambda d: None)
	monkeypatch.setattr(
		si,
		"list_sessions",
		lambda: [
			SessionSignal("opencode", "ses_parent", now - 5, None),
			SessionSignal("opencode", "ses_child1", now - 3, None),
			SessionSignal("opencode", "ses_child2", now - 2, None),
		],
	)

	assert [b["session_id"] for b in si.build_board()] == ["ses_parent"]
	assert si.board_line() == ""  # solo una sesión real → SILENT


def test_subsessions_lookup_is_non_fatal(tmp_path, monkeypatch):
	"""DB sin tabla `session` (u otro fallo) → no se filtra nada, no se rompe."""
	bad = tmp_path / "opencode.db"
	sqlite3.connect(bad).close()
	monkeypatch.setattr(si, "_opencode_db_path", lambda: bad)
	assert si._opencode_subsessions(["a", "b"]) == set()


def test_board_line_skips_db_with_single_active(monkeypatch):
	"""Con una sola sesión activa no se consulta `opencode.db` (camino barato)."""
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("opencode", "a", now, None), SessionSignal("opencode", "b", now - 9999, None)])

	def _boom(ids):
		raise AssertionError("no debería consultar opencode.db")

	monkeypatch.setattr(si, "_opencode_subsessions", _boom)
	assert si.board_line() == ""
