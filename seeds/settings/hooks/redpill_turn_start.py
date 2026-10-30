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

On ``UserPromptSubmit`` it also acknowledges board nudges: if the prompt carries
``msg=<event_id>`` markers, the matching ``event_deliveries`` rows of this soul
move to ``delivered`` (RFC-INTEROP-001 §12 bis). A nudge that lands mid-turn
arrives as a system reminder, fires no hook and stays ``handed_off``.

Non-fatal by contract: any error (unreadable or non-object payload included) is
swallowed and we exit 0 — the hook never blocks the IDE turn.
"""

import json
import os
import re
import sqlite3
import sys
import time
import uuid
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
	return token.strip().replace("/", "_").replace("__", "_").replace(":", "_")


def _state_root() -> Path:
	xdg = os.environ.get("XDG_DATA_HOME")
	base = Path(xdg) if xdg else Path.home() / ".local" / "share"
	return base / "red-pill" / "state"


def _turn_current(session_id: str) -> Path:
	return _state_root() / "external_turns" / "current" / f"{PROVIDER}__{_safe(session_id)}.json"


def _turn_archive(session_id: str, request_id: str) -> Path:
	return _state_root() / "external_turns" / "archive" / f"{PROVIDER}__{_safe(session_id)}__{_safe(request_id)}.json"


def _read_json(path: Path) -> dict | None:
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None
	return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(".json.tmp")
	tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	os.replace(tmp, path)


def _begin_turn(payload: dict, session_id: str) -> None:
	prompt = payload.get("prompt")
	if not isinstance(prompt, str) or not prompt.strip():
		return
	path = _turn_current(session_id)
	previous = _read_json(path)
	if previous and previous.get("status") == "pending":
		if previous.get("prompt") == prompt:
			return
		previous.update({"status": "aborted", "reason": "superseded", "ended_at": time.time()})
		_write_json(_turn_archive(session_id, str(previous.get("request_id") or "unknown")), previous)
	stamp = time.time()
	data = {
		"provider": PROVIDER,
		"session_id": session_id,
		"originator": f"{PROVIDER}:{session_id}",
		"request_id": f"{PROVIDER}:{session_id}:{int(stamp * 1000)}:{uuid.uuid4().hex[:8]}",
		"prompt": prompt,
		"cwd": str(payload.get("cwd") or ""),
		"model": None,
		"started_at": stamp,
		"status": "pending",
	}
	_write_json(path, data)


def _finish_turn(payload: dict, session_id: str, status: str, reason: str) -> None:
	path = _turn_current(session_id)
	data = _read_json(path)
	if not data:
		return
	data.update({"status": status, "reason": reason or None, "ended_at": time.time()})
	_write_json(_turn_archive(session_id, str(data.get("request_id") or "unknown")), data)
	try:
		path.unlink()
	except FileNotFoundError:
		pass


# Acuse por hook (RFC-INTEROP-001 §12 bis). COPIA LITERAL de `ACK_MARKER_RE` y
# `ACK_SQL` de `red_pill.session.delivery` (el hook no importa el kernel); el test
# de paridad falla si divergen.
ACK_MARKER_RE = re.compile(r"\bmsg=([0-9a-f]{32})\b")
ACK_SQL = (
	"UPDATE event_deliveries SET state = 'delivered', reason = ?, updated_at = ?"
	" WHERE event_id = ? AND state IN ('in_flight', 'handed_off')"
	" AND continuity_id IN (SELECT continuity_id FROM session_registry"
	" WHERE originator = ? AND ttl_state != 'expired')"
)


def _session_db() -> Path:
	"""${XDG_DATA_HOME}/red-pill/queue/session.db (= `core.paths.get_session_db`)."""
	xdg = os.environ.get("XDG_DATA_HOME")
	base = Path(xdg) if xdg else Path.home() / ".local" / "share"
	return base / "red-pill" / "queue" / "session.db"


def _ack_nudges(session_id: str, prompt: object) -> None:
	"""Si el prompt trae nudges del tablón, el arnés confirma la entrega.

	Sin marcador no se abre la BD (el caso normal cuesta una regex). La BD no se
	crea aquí: si no existe, no hay nada que acusar."""
	if not isinstance(prompt, str):
		return
	ids = sorted(set(ACK_MARKER_RE.findall(prompt)))
	db = _session_db()
	if not ids or not db.exists():
		return
	origin = f"{PROVIDER}:{session_id}"
	try:
		conn = sqlite3.connect(str(db), timeout=2.0)
		try:
			for event_id in ids:
				conn.execute(ACK_SQL, (f"ack_hook:{origin}"[:200], time.time(), event_id, origin))
			conn.commit()
		finally:
			conn.close()
	except Exception:
		pass


def _project_dir() -> str:
	"""Raíz del proyecto de la sesión (`CLAUDE_PROJECT_DIR`, que Claude Code exporta a
	los hooks). No sigue a los `cd`: de ahí sale la MISIÓN. El `cwd` del payload sí
	los sigue y de él salen la rama y el worktree (atributos), así que se guardan
	los dos (2026-10-30: con solo el cwd, salir del repo movía la misión a otro
	sitio; con solo la raíz, la rama decía `next` dentro de un worktree)."""
	return (os.environ.get("CLAUDE_PROJECT_DIR") or "").strip()


def _phase(payload: dict) -> str:
	return "end" if payload.get("hook_event_name") in END_EVENTS else "start"


def _bridge_token(token: str) -> str:
	"""Mismo saneo que `core.bridge._safe`: si no casan, el lector no encuentra el fichero."""
	return str(token).replace("/", "_").replace(":", "_").replace("__", "_")


def _session_bridge_path(session_id: str) -> Path:
	"""${STATE_DIR}/sessions/bridge/claude_code__<sid>.json — el bridge POR SESIÓN (D-BRIDGE)."""
	return _state_root() / "sessions" / "bridge" / f"{_bridge_token(PROVIDER)}__{_bridge_token(session_id)}.json"


def _write_bridge(session_id: str, cwd: str) -> None:
	"""Escribe el bridge del arnés al INICIO del turno (Alma y Coro A1/A2): el
	servidor MCP corre con cwd=kernel y necesita session_id + workspace del agente.
	CRÍTICO que sea en `UserPromptSubmit` (no sólo en Stop): si sólo se escribiera
	al final, el primer turno de una sesión nueva resolvería el bridge de la
	sesión anterior. Best-effort (nunca rompe el turno).

	Dos ficheros, como el plugin de opencode: el global (compat, último que
	escribe) y el POR SESIÓN, que además lleva el socket de mensajería de Claude
	Code (`CLAUDE_CODE_MESSAGING_SOCKET`): es el punto de inyección del tablón
	(transporte `claude_socket` de `core/soul_notify.py`, F6). El token del socket
	NO se guarda: es un secreto y en Linux la línea de auth es opcional."""
	data = {
		"provider": PROVIDER,
		"session_id": session_id,
		"workdir": (cwd or "").strip(),
		"updated_at": time.time(),
	}
	project = _project_dir()
	if project:
		data["project_dir"] = project
	try:
		path = _bridge_path()
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(".json.tmp")
		tmp.write_text(json.dumps(data), encoding="utf-8")
		os.replace(tmp, path)
	except Exception:
		pass
	socket_path = (os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET") or "").strip()
	if socket_path:
		data["messaging_socket"] = socket_path
	try:
		path = _session_bridge_path(session_id)
		path.parent.mkdir(parents=True, exist_ok=True)
		tmp = path.with_suffix(f".{os.getpid()}.tmp")
		tmp.write_text(json.dumps(data), encoding="utf-8")
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
		_begin_turn(payload, session_id)
		_ack_nudges(session_id, payload.get("prompt"))
	else:
		_finish_turn(payload, session_id, "aborted", str(payload.get("hook_event_name") or "session_end"))


def main() -> int:
	try:
		_run()
	except Exception:
		pass  # Nunca bloquear el turno por el latido.
	return 0


if __name__ == "__main__":
	sys.exit(main())
