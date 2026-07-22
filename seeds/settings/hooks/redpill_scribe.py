#!/usr/bin/env python3
"""Red Pill Scribe — Claude Code Stop hook (RAW CAPTURE LAYER).

Parity with the opencode redpill-scribe.js plugin and opencode.py:_scribe_relay:
writes each turn's (user_prompt, agent_response, model) pair into the
`interactions` table of bunker.db. Deterministic — the harness runs it on Stop,
so capture no longer depends on the agent invoking the scribe relay by hand.

Reads the Stop hook JSON from stdin ({session_id, transcript_path, ...}),
parses the transcript JSONL to recover the last real user prompt and the
assistant's full response for the turn, and inserts one row.

Design notes:
  - Non-fatal by contract: any error is swallowed and we exit 0 so a scribe
    failure never blocks the turn.
  - Dedup: Stop also fires on clear/resume/compact. We remember the last
    assistant message uuid written per session and skip if unchanged, so a
    Stop with no new turn does not duplicate the previous row.
  - Truncation matches the Python/JS writers: prompt[:2000], response[:5000].
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

PROMPT_MAX = 2000
RESPONSE_MAX = 5000


def _data_dir() -> Path:
	"""~/.local/share/red-pill, honoring XDG_DATA_HOME (matches platformdirs)."""
	xdg = os.environ.get("XDG_DATA_HOME")
	base = Path(xdg) if xdg else Path.home() / ".local" / "share"
	return base / "red-pill"


DB_PATH = _data_dir() / "db" / "bunker.db"
STATE_DIR = _data_dir() / "scribe-state"


def _text_from_content(content) -> str:
	"""Extract plain text from a message.content that is a str or block list."""
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		out = []
		for block in content:
			if isinstance(block, dict) and block.get("type") == "text":
				out.append(block.get("text", ""))
		return "\n".join(t for t in out if t)
	return ""


def _has_tool_result(content) -> bool:
	return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _parse_transcript(path: str):
	"""Return (user_prompt, agent_response, model, marker) for the last turn.

	marker = uuid of the last assistant entry, used for dedup.
	"""
	entries = []
	with open(path, encoding="utf-8") as f:
		for raw in f:
			raw = raw.strip()
			if not raw:
				continue
			try:
				obj = json.loads(raw)
			except json.JSONDecodeError:
				continue
			if not isinstance(obj, dict):
				continue
			# Main chain only — ignore subagent sidechains and meta entries.
			if obj.get("isSidechain") or obj.get("isMeta"):
				continue
			entries.append(obj)

	# Find the last genuine user prompt (typed text, not a tool_result turn).
	last_user_idx = None
	for i in range(len(entries) - 1, -1, -1):
		e = entries[i]
		if e.get("type") != "user":
			continue
		content = (e.get("message") or {}).get("content")
		if _has_tool_result(content):
			continue
		if _text_from_content(content).strip():
			last_user_idx = i
			break

	if last_user_idx is None:
		return None

	user_prompt = _text_from_content((entries[last_user_idx].get("message") or {}).get("content"))

	# Assistant response = all assistant text after that user prompt.
	resp_parts = []
	model = None
	marker = None
	for e in entries[last_user_idx + 1 :]:
		if e.get("type") != "assistant":
			continue
		msg = e.get("message") or {}
		txt = _text_from_content(msg.get("content"))
		if txt:
			resp_parts.append(txt)
		if msg.get("model"):
			model = msg.get("model")
		if e.get("uuid"):
			marker = e.get("uuid")

	agent_response = "\n".join(resp_parts)
	return user_prompt, agent_response, model, marker


def _dedup_seen(session_id: str, marker: str) -> bool:
	"""True if this marker was already written for this session."""
	if not session_id or not marker:
		return False
	STATE_DIR.mkdir(parents=True, exist_ok=True)
	state = STATE_DIR / f"{session_id}.last"
	try:
		if state.read_text(encoding="utf-8").strip() == marker:
			return True
	except OSError:
		pass
	state.write_text(marker, encoding="utf-8")
	return False


def _write(user_prompt: str, agent_response: str, model):
	conn = sqlite3.connect(str(DB_PATH))
	try:
		conn.execute("PRAGMA journal_mode=WAL")
		conn.execute(
			"""CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_prompt TEXT,
                agent_response TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                model TEXT
            )"""
		)
		cols = [r[1] for r in conn.execute("PRAGMA table_info(interactions)").fetchall()]
		if "model" not in cols:
			conn.execute("ALTER TABLE interactions ADD COLUMN model TEXT")
		conn.execute(
			"""INSERT INTO interactions (user_prompt, agent_response, timestamp, model)
               VALUES (?, ?, CURRENT_TIMESTAMP, ?)""",
			(user_prompt[:PROMPT_MAX], agent_response[:RESPONSE_MAX], model),
		)
		conn.commit()
	finally:
		conn.close()


def main() -> int:
	try:
		payload = json.load(sys.stdin)
	except Exception:
		return 0

	transcript_path = payload.get("transcript_path")
	session_id = payload.get("session_id", "")
	if not transcript_path or not os.path.isfile(transcript_path):
		return 0

	try:
		parsed = _parse_transcript(transcript_path)
		if not parsed:
			return 0
		user_prompt, agent_response, model, marker = parsed
		if not user_prompt and not agent_response:
			return 0
		if _dedup_seen(session_id, marker):
			return 0
		_write(user_prompt, agent_response, model)
	except Exception:
		# Never block the turn on a scribe failure.
		return 0
	return 0


if __name__ == "__main__":
	sys.exit(main())
