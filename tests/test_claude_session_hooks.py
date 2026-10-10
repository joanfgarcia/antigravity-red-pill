"""Hooks de Claude Code (seeds/settings/hooks): latido de sesión y contrato non-fatal.

Se ejecutan como los lanza el IDE (subproceso, JSON por stdin) con un
`XDG_DATA_HOME` temporal: nunca tocan el estado real del operador.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "seeds" / "settings" / "hooks"
HOOKS = ("redpill_turn_start.py", "redpill_scribe.py")


def _run_hook(script: str, stdin: str, data_home: Path) -> subprocess.CompletedProcess:
	env = {**os.environ, "XDG_DATA_HOME": str(data_home)}
	return subprocess.run(
		[sys.executable, str(HOOKS_DIR / script)],
		input=stdin,
		capture_output=True,
		text=True,
		env=env,
		timeout=30,
	)


def _live(data_home: Path) -> Path:
	return data_home / "red-pill" / "state" / "sessions" / "live"


@pytest.mark.parametrize("script", HOOKS)
@pytest.mark.parametrize(
	"stdin",
	[
		"",
		"no es json",
		"[]",
		'"texto"',
		"null",
		"42",
		'{"session_id": 5}',
		'{"session_id": ["x"], "transcript_path": 7}',
		'{"session_id": "s1", "transcript_path": {"no": "str"}}',
	],
)
def test_hooks_never_fail(script, stdin, tmp_path):
	"""Payload ilegible o que no es un objeto → exit 0 (el hook nunca bloquea el turno)."""
	res = _run_hook(script, stdin, tmp_path)
	assert res.returncode == 0, res.stderr


def test_turn_start_marks_start(tmp_path):
	res = _run_hook("redpill_turn_start.py", json.dumps({"session_id": "uuid-1", "hook_event_name": "UserPromptSubmit"}), tmp_path)
	assert res.returncode == 0, res.stderr
	assert sorted(p.name for p in _live(tmp_path).iterdir()) == ["claude_code__uuid-1.start"]


def test_scribe_marks_end_without_transcript(tmp_path):
	res = _run_hook("redpill_scribe.py", json.dumps({"session_id": "uuid-2"}), tmp_path)
	assert res.returncode == 0, res.stderr
	assert sorted(p.name for p in _live(tmp_path).iterdir()) == ["claude_code__uuid-2.end"]


@pytest.mark.parametrize("event", ["StopFailure", "SessionEnd"])
def test_turn_closing_events_mark_end(event, tmp_path):
	"""StopFailure (salta en lugar de Stop) y SessionEnd cierran el turno: `.end`, no `.start`."""
	res = _run_hook("redpill_turn_start.py", json.dumps({"session_id": "uuid-3", "hook_event_name": event, "error": "rate_limit"}), tmp_path)
	assert res.returncode == 0, res.stderr
	assert sorted(p.name for p in _live(tmp_path).iterdir()) == ["claude_code__uuid-3.end"]


def test_seed_registers_heartbeat_events():
	"""El fragmento registra el latido en todos los eventos que abren/cierran turno."""
	seed = json.loads((REPO_ROOT / "seeds" / "settings" / "claude-code.json").read_text(encoding="utf-8"))
	commands = {event: [h["command"] for block in blocks for h in block["hooks"]] for event, blocks in seed["hooks"].items()}
	for event in ("UserPromptSubmit", "StopFailure", "SessionEnd"):
		assert any(c.endswith("/.claude/hooks/redpill_turn_start.py") for c in commands[event]), event
	assert any(c.endswith("/.claude/hooks/redpill_scribe.py") for c in commands["Stop"])


# ── Alma y Coro (paridad claude_code) ───────────────────────────────────────
def _make_queue_db(data_home: Path) -> Path:
	import sqlite3

	queue = data_home / "red-pill" / "queue"
	queue.mkdir(parents=True, exist_ok=True)
	db_path = queue / "bunker_queue.db"
	conn = sqlite3.connect(str(db_path))
	conn.execute(
		"CREATE TABLE memory_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, prompt TEXT NOT NULL, "
		"response TEXT NOT NULL, role TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at REAL, "
		"category TEXT DEFAULT 'mixed', originator TEXT, model TEXT, content_hash TEXT, session_id TEXT, affinity TEXT)"
	)
	conn.commit()
	conn.close()
	return db_path


def _write_transcript(tmp_path: Path, tag: str) -> Path:
	entries = [
		{"type": "user", "uuid": "u0", "message": {"role": "user", "content": "¿qué tal el plan?"}},
		{"type": "assistant", "uuid": "a0", "message": {"role": "assistant", "model": "claude-x", "content": [{"type": "text", "text": "Vamos con la fase 0a."}]}},
		{"type": "user", "uuid": "u1", "message": {"role": "user", "content": [{"type": "tool_result", "content": tag}]}},
	]
	path = tmp_path / "transcript.jsonl"
	path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries), encoding="utf-8")
	return path


TAG = '<session continuity_id="cid-hook" leg="claude_code:uuid-h1" mission="repo:feat/x"/>'


def test_scribe_writes_composite_originator(tmp_path):
	import sqlite3

	db_path = _make_queue_db(tmp_path)
	tr = _write_transcript(tmp_path, TAG)
	res = _run_hook("redpill_scribe.py", json.dumps({"session_id": "uuid-h1", "transcript_path": str(tr)}), tmp_path)
	assert res.returncode == 0, res.stderr
	conn = sqlite3.connect(str(db_path))
	try:
		row = conn.execute("SELECT originator, session_id FROM memory_queue ORDER BY id DESC LIMIT 1").fetchone()
	finally:
		conn.close()
	assert row is not None
	assert row[0] == "claude_code:uuid-h1"  # cuerpo compuesto (provider:sesión nativa)
	assert row[1] == "uuid-h1"


def test_turn_start_writes_bridge(tmp_path):
	# El bridge se escribe al INICIO del turno (UserPromptSubmit), no en Stop: así
	# el primer turno de una sesión nueva no hereda el bridge de la anterior.
	payload = {"session_id": "uuid-h1", "hook_event_name": "UserPromptSubmit", "cwd": "/ws/proj"}
	res = _run_hook("redpill_turn_start.py", json.dumps(payload), tmp_path)
	assert res.returncode == 0, res.stderr
	bridge = tmp_path / "red-pill" / "state" / "claude_code_session.json"
	assert bridge.exists()
	data = json.loads(bridge.read_text(encoding="utf-8"))
	assert data["session_id"] == "uuid-h1"
	assert data["workdir"] == "/ws/proj"
	assert data["provider"] == "claude_code"


def test_scribe_does_not_write_bridge(tmp_path):
	# Stop NO reescribe el bridge (evita dejar una sesión muerta como fresca).
	tr = _write_transcript(tmp_path, TAG)
	_run_hook("redpill_scribe.py", json.dumps({"session_id": "uuid-h1", "transcript_path": str(tr), "cwd": "/ws/proj"}), tmp_path)
	assert not (tmp_path / "red-pill" / "state" / "claude_code_session.json").exists()
