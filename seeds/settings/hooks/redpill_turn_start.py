#!/usr/bin/env python3
"""Red Pill Turn Start — Claude Code UserPromptSubmit hook (SESSION LIVENESS).

Marks the START of a turn (RFC-DESPERTAR-001, P4): touches an empty file
``${STATE_DIR}/sessions/live/claude_code__<session_id>.start`` whose mtime is the
signal. Symmetric to the ``.end`` touch in ``redpill_scribe.py`` (Stop hook).
No content; the pair (start, end) tells "alguien está tocando" vs "alguien ha
tocado" (ver ``red_pill.core.session_liveness``).

Fires when the Operator submits the prompt — before tools/thinking — so the
`start` is a clean turn boundary.

Non-fatal by contract: any error (unreadable or non-object payload included) is
swallowed and we exit 0 — the hook never blocks the IDE turn.
"""

import json
import os
import sys
from pathlib import Path

PROVIDER = "claude_code"


def _live_dir() -> Path:
	"""${STATE_DIR}/sessions/live, honoring XDG_DATA_HOME (matches the kernel)."""
	xdg = os.environ.get("XDG_DATA_HOME")
	base = Path(xdg) if xdg else Path.home() / ".local" / "share"
	return base / "red-pill" / "state" / "sessions" / "live"


def _safe(token: str) -> str:
	return token.strip().replace("/", "_").replace("__", "_")


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
	live = _live_dir()
	live.mkdir(parents=True, exist_ok=True)
	(live / f"{_safe(PROVIDER)}__{_safe(session_id)}.start").touch(exist_ok=True)


def main() -> int:
	try:
		_run()
	except Exception:
		pass  # Nunca bloquear el turno por el latido.
	return 0


if __name__ == "__main__":
	sys.exit(main())
