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
