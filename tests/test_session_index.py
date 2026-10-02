import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

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


def _make_db(rows):
	fd, path = tempfile.mkstemp(suffix=".db")
	os.close(fd)
	con = sqlite3.connect(path)
	con.execute("CREATE TABLE part (id INTEGER PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")
	for i, d in enumerate(rows):
		con.execute(
			"INSERT INTO part (session_id, time_created, data) VALUES (?, ?, ?)",
			("s1", i, json.dumps(d)),
		)
	con.commit()
	con.close()
	return path


def test_touched_paths_extraction(monkeypatch):
	rows = [
		{"type": "tool", "tool": "read", "state": {"input": {"filePath": "/home/user/proj/a.md"}}},
		{"type": "tool", "tool": "bash", "state": {"input": {"command": "cd /home/user/proj/b && ls", "workdir": "/home/user/proj/b"}}},
		{"type": "tool", "tool": "glob", "state": {"input": {"path": "/home/user/proj/c", "pattern": "**/*.py"}}},
		{"type": "text", "text": "no soy tool"},
	]
	monkeypatch.setattr(si, "_opencode_db_path", lambda: Path(_make_db(rows)))
	assert si._touched_paths("s1") == [
		"/home/user/proj/a.md",
		"/home/user/proj/b",
		"/home/user/proj/c",
	]


def test_touched_paths_ordered_by_last_use_and_relative_to_session(monkeypatch):
	rows = [
		{"type": "tool", "tool": "read", "state": {"input": {"filePath": "/srv/a/x.py"}}},
		{"type": "tool", "tool": "read", "state": {"input": {"filePath": "/srv/b/y.py"}}},
		{"type": "tool", "tool": "read", "state": {"input": {"filePath": "/srv/a/x.py"}}},
		{"type": "tool", "tool": "glob", "state": {"input": {"path": ".", "pattern": "*"}}},
	]
	monkeypatch.setattr(si, "_opencode_db_path", lambda: Path(_make_db(rows)))
	assert si._touched_paths("s1", base_dir="/srv/c") == ["/srv/b/y.py", "/srv/a/x.py", "/srv/c"]
	# sin directorio de sesión, las relativas no se resuelven contra el cwd del proceso
	assert si._touched_paths("s1") == ["/srv/b/y.py", "/srv/a/x.py"]


def test_command_paths_keeps_tilde_and_quoted_spaces():
	cmd = "cat '/srv/my docs/n.md' ~/notes/t.md --out=/tmp/o.txt && cd /srv/a&&ls"
	assert si._command_paths(cmd) == ["/srv/my docs/n.md", "~/notes/t.md", "/tmp/o.txt", "/srv/a"]
	assert si._command_paths("echo 'unterminated /srv/z") == ["/srv/z"]


@pytest.mark.parametrize(
	"cmd, expected",
	[
		# relativo con una barra dentro: no es una ruta absoluta embebida
		("tail awakening/2026-10-01T03.log", []),
		("ls ./src/red_pill/x.py ../a/b", []),
		# URLs: ni `//host/...` ni el path de la URL
		("curl -s https://example.com/api/v1", []),
		# embebidas tras separador: `=`, `:`, operador shell, blanco de un token entrecomillado
		("PATH=/a/bin:/b/bin cmd", ["/a/bin", "/b/bin"]),
		('bash -c "cd /srv/x && ls"', ["/srv/x"]),
		("cat <(sort /srv/f)", ["/srv/f"]),
		("tar -C/srv/out -xf x.tgz", []),
	],
)
def test_command_paths_only_embedded_after_separator(cmd, expected):
	assert si._command_paths(cmd) == expected


def test_touched_paths_missing_db(monkeypatch):
	monkeypatch.setattr(si, "_opencode_db_path", lambda: Path("/no/existe/opencode.db"))
	assert si._touched_paths("s1") == []


def test_build_board_projects_by_paths(monkeypatch):
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("opencode", "sx", now - 1, None)])
	monkeypatch.setattr(si, "_opencode_meta", lambda sid: {"directory": "/home/user/IA", "title": "T", "model": "m"})
	monkeypatch.setattr(si, "_origin_for", lambda p, s: "user")
	monkeypatch.setattr(si, "_owning_workspace", lambda d: "sharing")
	monkeypatch.setattr(si, "_touched_paths", lambda sid, base_dir=None: ["/home/user/school/x.py", "/home/user/sharing/y.py"])
	monkeypatch.setattr(si, "_theme_client", lambda: object())
	monkeypatch.setattr(si, "_rolling_topic", lambda sid, client=None: "un tema")
	captured = {}

	def _fake_infer(paths):
		captured["paths"] = list(paths)
		return ["sharing", "school"]

	monkeypatch.setattr(si, "infer_workspaces", _fake_infer)

	b = si.build_board()[0]
	# más reciente primero: el proyecto es el de la última ruta tocada
	assert captured["paths"] == ["/home/user/sharing/y.py", "/home/user/school/x.py"]
	assert b["project"] == "sharing"
	assert b["projects"] == ["sharing", "school"]
	assert b["topic"] == "un tema"
	assert b["touched_files"] == 2


def test_build_board_without_theme_client_has_no_topic(monkeypatch):
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("claude_code", "c1", now - 1, None)])
	monkeypatch.setattr(si, "_origin_for", lambda p, s: "user")
	monkeypatch.setattr(si, "_theme_client", lambda: None)
	monkeypatch.setattr(si, "_rolling_topic", lambda sid, client=None: "NO-DEBE-LLEGAR")
	assert si.build_board()[0]["topic"] is None


class _P:
	def __init__(self, payload):
		self.payload = payload


class _Client:
	def scroll(self, *a, **k):
		return [
			_P({"tag_theme": "tema-viejo", "tagged_at": 100}),
			_P({"tag_theme": "tema-nuevo", "tagged_at": 200}),
			_P({"tagged_at": 999}),
		], None


class _PagedClient:
	"""Dos páginas: el tema más reciente llega en la SEGUNDA (orden uuid arbitrario)."""

	def __init__(self):
		self.offsets = []

	def scroll(self, *a, offset=None, **k):
		self.offsets.append(offset)
		if offset is None:
			return [_P({"tag_theme": "antiguo", "tagged_at": 10})], "next"
		return [_P({"tag_theme": "reciente", "tagged_at": 20})], None


def test_query_latest_theme_reads_every_page():
	c = _PagedClient()
	assert si._query_latest_theme("s1", client=c) == "reciente"
	assert c.offsets == [None, "next"]


def test_query_latest_theme():
	assert si._query_latest_theme("s1", client=_Client()) == "tema-nuevo"


def test_rolling_topic_disabled(monkeypatch):
	monkeypatch.setattr("red_pill.core.realtime_tag.enabled", lambda: False)
	monkeypatch.setattr(si, "_query_latest_theme", lambda sid, client=None: "NO-DEBE-LLEGAR")
	assert si._rolling_topic("s1") is None


def test_rolling_topic_enabled(monkeypatch):
	monkeypatch.setattr("red_pill.core.realtime_tag.enabled", lambda: True)
	monkeypatch.setattr(si, "_query_latest_theme", lambda sid, client=None: "tema")
	assert si._rolling_topic("s1") == "tema"


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


def test_build_board_enriched(tmp_path, monkeypatch):
	now = time.time()
	workdir = str(tmp_path / "sharing")
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("opencode", "ses_x", now - 1, None)])
	monkeypatch.setattr(si, "_opencode_meta", lambda sid: {"directory": workdir, "title": "T", "model": "m"})
	monkeypatch.setattr(si, "_origin_for", lambda p, s: "awakening")
	monkeypatch.setattr(si, "_owning_workspace", lambda d: "sharing")
	monkeypatch.setattr(si, "_touched_paths", lambda sid, base_dir=None: [])
	monkeypatch.setattr(si, "_rolling_topic", lambda sid, client=None: None)

	board = si.build_board()
	assert len(board) == 1
	b = board[0]
	assert b["provider"] == "opencode"
	assert b["origin"] == "awakening"
	assert b["project"] == "sharing"
	assert b["directory"] == workdir
	assert b["projects"] == ["sharing"]
	assert b["title"] == "T"
	assert b["model"] == "m"
	assert b["in_flight"] is True
	assert b["active"] is True


def test_build_board_non_opencode_has_no_meta(monkeypatch):
	now = time.time()
	monkeypatch.setattr(si, "_active_seconds", lambda: 600)
	monkeypatch.setattr(si, "list_sessions", lambda: [SessionSignal("claude_code", "uuid-1", now - 2, now - 1)])
	monkeypatch.setattr(si, "_touched_paths", lambda sid, base_dir=None: [])
	monkeypatch.setattr(si, "_rolling_topic", lambda sid, client=None: None)
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


@pytest.mark.parametrize(
	"raw, expected",
	[
		('{"id":"deepseek-v4-pro","providerID":"opencode-go","variant":"default"}', "opencode-go/deepseek-v4-pro"),
		('{"id":"solo-id"}', "solo-id"),
		("{}", None),
		(None, None),
		("", None),
		("provider/model", "provider/model"),
	],
)
def test_format_model(raw, expected):
	assert si._format_model(raw) == expected


def test_opencode_meta_renders_model(tmp_path, monkeypatch):
	db = _opencode_db(tmp_path / "opencode.db", [("ses_a", None, "/w", "T", '{"id":"m1","providerID":"prov","variant":"max"}')])
	monkeypatch.setattr(si, "_opencode_db_path", lambda: db)
	assert si._opencode_meta("ses_a") == {"directory": "/w", "title": "T", "model": "prov/m1"}


def test_render_board_separates_live_from_recent():
	now = 10_000.0
	board = [
		{
			"provider": "opencode",
			"session_id": "viva",
			"origin": "user",
			"active": True,
			"in_flight": True,
			"last_activity": now - 60,
			"model": "p/m",
		},
		{"provider": "claude_code", "session_id": "vieja", "origin": "user", "active": False, "in_flight": False, "last_activity": now - 7200},
		{"provider": "claude_code", "session_id": "colgada", "origin": "user", "active": False, "in_flight": True, "last_activity": now - 1800},
	]
	text = si.render_board(board, active_min=10, now=now)
	head, rest = text.split("\n", 1)
	assert head == "--- SESSION BOARD: 1 viva(s) · 2 reciente(s) ---"
	live_part, recent_part = rest.split("Recientes", 1)
	assert "viva" in live_part and "vieja" not in live_part and "colgada" not in live_part
	assert "modelo=p/m" in live_part
	assert "vieja · user · idle · hace 2 h" in recent_part
	assert "colgada · user · en vuelo > 10 min (¿huérfana?)" in recent_part


def test_render_board_empty():
	assert si.render_board([], active_min=10) == "[SESSION BOARD] Sin sesiones vivas ni recientes."


def test_write_index_is_atomic(tmp_path, monkeypatch):
	monkeypatch.setattr(si, "get_state_dir", lambda: tmp_path)
	path = si.write_index([{"provider": "opencode", "session_id": "a"}])
	assert path == tmp_path / "sessions_index.json"
	assert si.read_index() == [{"provider": "opencode", "session_id": "a"}]
	assert [p.name for p in tmp_path.iterdir()] == ["sessions_index.json"]  # sin .tmp residual


def test_write_index_failure_leaves_previous(tmp_path, monkeypatch):
	monkeypatch.setattr(si, "get_state_dir", lambda: tmp_path)
	si.write_index([{"session_id": "previo"}])

	def _boom(src, dst):
		raise OSError("disco lleno")

	monkeypatch.setattr(si.os, "replace", _boom)
	si.write_index([{"session_id": "nuevo"}])
	assert si.read_index() == [{"session_id": "previo"}]
	assert [p.name for p in tmp_path.iterdir()] == ["sessions_index.json"]


def test_render_board_shows_topic_and_other_projects():
	b = {
		"provider": "opencode",
		"session_id": "s1",
		"origin": "user",
		"active": True,
		"in_flight": True,
		"last_activity": 100.0,
		"project": "sharing",
		"projects": ["sharing", "school"],
		"topic": "auditoría",
	}
	out = si.render_board([b], active_min=10, now=100.0)
	assert "proyecto=sharing (+school)" in out
	assert "tema=auditoría" in out
