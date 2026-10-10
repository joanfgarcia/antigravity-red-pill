#!/usr/bin/env python3
"""Red Pill Turn Start — Claude Code session heartbeat hook (SESSION LIVENESS).

Marks the START of a turn (RFC-DESPERTAR-001, P4): touches an empty file
``${STATE_DIR}/sessions/live/claude_code__<session_id>.start`` whose mtime is the
signal. Symmetric to the ``.end`` touch in ``redpill_scribe.py`` (Stop hook).
No content; the pair (start, end) tells "alguien está tocando" vs "alguien ha
tocado" (ver ``red_pill.core.session_liveness``).

Registered on ``UserPromptSubmit`` (fires when the Operator submits the prompt —
before tools/thinking — so the `start` is a clean turn boundary) and on the
events that close a turn WITHOUT ``Stop``, which mark ``.end`` instead
(``hook_event_name``, verified in Claude Code 2.1.217):

- ``StopFailure``: the turn ended on an API error (rate limit, auth, overload…);
it fires *instead of* ``Stop``.
- ``SessionEnd``: the session is closing (exit, /clear…), maybe mid-turn.

An Esc interrupt fires no hook at all: that `.start` stays "in flight" until the
next turn or ``SESSION_ACTIVE_MIN``.

Non-fatal by contract: any error (unreadable or non-object payload included) is
swallowed and we exit 0 — the hook never blocks the IDE turn.
"""

import json
import os
import sys
import time
from pathlib import Path

PROVIDER = "claude_code"
# Eventos que cierran el turno sin `Stop` → `.end` (el resto marca `.start`).
END_EVENTS = frozenset({"StopFailure", "SessionEnd"})


def _live_dir() -> Path:
	"""${STATE_DIR}/sessions/live, honoring XDG_DATA_HOME (matches the kernel)."""
	xdg = os.environ.get("XDG_DATA_HOME")
	base = Path(xdg) if xdg else Path.home() / ".local" / "share"
	return base / "red-pill" / "state" / "sessions" / "live"


def _bridge_path() -> Path:
	"""${STATE_DIR}/claude_code_session.json — lo lee `_harness_bridge` (MCP)."""
	xdg = os.environ.get("XDG_DATA_HOME")
	base = Path(xdg) if xdg else Path.home() / ".local" / "share"
	return base / "red-pill" / "state" / "claude_code_session.json"


def _safe(token: str) -> str:
	return token.strip().replace("/", "_").replace("__", "_")


def _phase(payload: dict) -> str:
	return "end" if payload.get("hook_event_name") in END_EVENTS else "start"


def _write_bridge(session_id: str, cwd: str) -> None:
	"""Escribe el bridge del arnés al INICIO del turno (Alma y Coro A1/A2): el
	servidor MCP corre con cwd=kernel y necesita session_id + workspace del agente.
	CRÍTICO que sea en `UserPromptSubmit` (no sólo en Stop): si sólo se escribiera
	al final, el primer turno de una sesión nueva resolvería el bridge de la
	sesión anterior. Best-effort (nunca rompe el turno)."""
	try:
		payload = json.dumps(
			{
				"provider": PROVIDER,
				"session_id": session_id,
				"workdir": (cwd or "").strip(),
				"updated_at": time.time(),
			}
		)
		path = _bridge_path()
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(".json.tmp")
		tmp.write_text(payload, encoding="utf-8")
		os.replace(tmp, path)
	except Exception:
		pass


def _run() -> None:
	try:
		payload = json.load(sys.stdin)
	except Exception:
		return
	if not isinstance(payload, dict):
		return
	session_id = payload.get("session_id")
	if not isinstance(session_id, str) or not session_id.strip():
		return
	phase = _phase(payload)
	live = _live_dir()
	live.mkdir(parents=True, exist_ok=True)
	(live / f"{_safe(PROVIDER)}__{_safe(session_id)}.{phase}").touch(exist_ok=True)
	# El bridge sólo se refresca al INICIO del turno (sesión activa); en los
	# eventos de cierre no se reescribe (evita dejar una sesión muerta como fresca).
	if phase == "start":
		cwd = payload.get("cwd")
		_write_bridge(session_id, cwd if isinstance(cwd, str) else "")


def main() -> int:
	try:
		_run()
	except Exception:
		pass  # Nunca bloquear el turno por el latido.
	return 0


if __name__ == "__main__":
	sys.exit(main())
