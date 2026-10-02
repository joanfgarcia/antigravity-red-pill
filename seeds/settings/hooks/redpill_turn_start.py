#!/usr/bin/env python3
"""Red Pill Turn Start — Claude Code UserPromptSubmit hook (SESSION LIVENESS).

Marks the START of a turn (RFC-DESPERTAR-001, P4): touches an empty file
``${STATE_DIR}/sessions/live/claude_code__<session_id>.start`` whose mtime is the
signal. Symmetric to the ``.end`` touch in ``redpill_scribe.py`` (Stop hook).
No content; the pair (start, end) tells "alguien está tocando" vs "alguien ha
tocado" (ver ``red_pill.core.session_liveness``).

Fires when the Operator submits the prompt — before tools/thinking — so the
`start` is a clean turn boundary.

Non-fatal by contract: any error is swallowed and we exit 0.
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


def main() -> int:
	try:
		payload = json.load(sys.stdin)
	except Exception:
		return 0
	session_id = payload.get("session_id", "")
	if not session_id:
		return 0
	try:
		live = _live_dir()
		live.mkdir(parents=True, exist_ok=True)
		(live / f"{_safe(PROVIDER)}__{_safe(session_id)}.start").touch(exist_ok=True)
	except Exception:
		pass
	return 0


if __name__ == "__main__":
	sys.exit(main())
