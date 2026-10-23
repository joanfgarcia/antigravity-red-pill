"""Detección de inactividad del despertar autónomo (29 jul 2026).

La asimetría original: Antigravity tenía doble señal (interceptor + transcripts
en disco) mientras Claude Code y opencode dependían de que el agente llamara al
handshake — una sesión amnésica o un run headless dejaba al operador "offline"
y el despertar lo interrumpía en plena faena. Aquí se fija el contrato: la
actividad EN DISCO de cualquiera de los tres IDEs cuenta como presencia.
"""

import os
import time

import pytest

from red_pill.swarm import autonomous_cron


@pytest.fixture
def silent_world(tmp_path, monkeypatch):
	"""Un mundo sin señal alguna: todos los directorios existen pero rancios."""
	state = tmp_path / "state"
	brain = tmp_path / "brain"
	claude = tmp_path / "claude_projects"
	opencode = tmp_path / "opencode"
	pi = tmp_path / "pi_sessions"
	for d in (state, brain, claude, opencode, pi):
		d.mkdir()
	monkeypatch.setattr(autonomous_cron, "get_state_dir", lambda: state)
	monkeypatch.setattr(autonomous_cron, "get_antigravity_brain_dir", lambda: brain)
	monkeypatch.setattr(autonomous_cron, "CLAUDE_PROJECTS_DIR", claude)
	monkeypatch.setattr(autonomous_cron, "OPENCODE_DATA_DIR", opencode)
	monkeypatch.setattr(autonomous_cron, "PI_SESSIONS_DIR", pi)
	monkeypatch.setattr(autonomous_cron, "read_origins", lambda _provider=None: {})
	return {"state": state, "brain": brain, "claude": claude, "opencode": opencode, "pi": pi}


def _stale(path, hours=3):
	path.write_text("x", encoding="utf-8")
	old = time.time() - hours * 3600
	os.utime(path, (old, old))


def test_idle_when_every_signal_is_stale(silent_world):
	_stale(silent_world["state"] / "last_user_activity.txt")
	(silent_world["brain"] / "s1").mkdir()
	_stale(silent_world["brain"] / "s1" / "transcript.jsonl", hours=5)
	(silent_world["claude"] / "proj").mkdir()
	_stale(silent_world["claude"] / "proj" / "ses.jsonl", hours=5)
	_stale(silent_world["opencode"] / "opencode.db", hours=5)
	assert autonomous_cron.is_ide_idle(3600) is True


def test_fresh_claude_code_transcript_means_operator_present(silent_world):
	"""Una tarde picando en Claude Code SIN handshake ya no es 'offline'."""
	project = silent_world["claude"] / "mi-proyecto"
	project.mkdir()
	(project / "sesion.jsonl").write_text('{"role": "user"}\n', encoding="utf-8")
	assert autonomous_cron.is_ide_idle(3600) is False


def test_fresh_opencode_db_means_operator_present(silent_world):
	(silent_world["opencode"] / "opencode.db-wal").write_text("wal", encoding="utf-8")
	assert autonomous_cron.is_ide_idle(3600) is False


def test_fresh_antigravity_transcript_still_counts(silent_world):
	session = silent_world["brain"] / "conv-1"
	session.mkdir()
	(session / "transcript.jsonl").write_text("{}", encoding="utf-8")
	assert autonomous_cron.is_ide_idle(3600) is False


def test_fresh_activity_touch_still_counts(silent_world):
	(silent_world["state"] / "last_user_activity.txt").touch()
	assert autonomous_cron.is_ide_idle(3600) is False


PI_SID = "01a16785-9a3a-7279-8f01-1d1b2da6c5c5"


def test_fresh_pi_session_means_operator_present(silent_world):
	"""Trabajar en una sesión de Pi (sin handshake por turno) no es 'offline'."""
	session = silent_world["pi"] / "--home-joan--"
	session.mkdir()
	(session / f"2026-10-23T06-49-31-451Z_{PI_SID}.jsonl").write_text("{}\n", encoding="utf-8")
	assert autonomous_cron.is_ide_idle(3600) is False


def test_fresh_pi_awakening_session_does_not_count(silent_world, monkeypatch):
	"""Un run headless de awakening no maquilla la ausencia del Operador."""
	monkeypatch.setattr(autonomous_cron, "read_origins", lambda _provider=None: {PI_SID: {"origin": "awakening", "ts": 0}})
	session = silent_world["pi"] / "--home-joan--"
	session.mkdir()
	(session / f"2026-10-23T06-49-31-451Z_{PI_SID}.jsonl").write_text("{}\n", encoding="utf-8")
	assert autonomous_cron.is_ide_idle(3600) is True
