"""Tests for OpenCodeBridge (swarm/bridges/opencode.py).

The bridge shells out to the `opencode` CLI, but its logic — stream parsing,
handshake preamble, scribe relay, model/effort arg mapping, capabilities, and the
prompt/continue round-trips — is pure or mockable. `opencode` need not be
installed: we pass an explicit binary path to bypass the PATH check and mock
`_run_opencode`/`subprocess.run`.
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from red_pill.swarm.bridges.base import BackendType
from red_pill.swarm.bridges.opencode import OpenCodeBridge


@pytest.fixture
def bridge():
	# Explicit path bypasses shutil.which() so the CLI need not be installed.
	return OpenCodeBridge(opencode_path="/bin/true")


# ── Stream parsing (pure) ─────────────────────────────────────────────────────
class TestParseJsonStream:
	def test_extracts_session_and_text(self):
		stream = "\n".join(
			[
				json.dumps({"type": "step_start", "sessionID": "ses_abc"}),
				json.dumps({"type": "text", "part": {"text": "Hola"}}),
				json.dumps({"type": "text", "part": {"text": " mundo"}}),
			]
		)
		out = OpenCodeBridge._parse_json_stream(stream)
		assert out == {"session_id": "ses_abc", "text": "Hola mundo"}

	def test_ignores_non_json_and_blank_lines(self):
		stream = "not json\n\n" + json.dumps({"type": "text", "part": {"text": "x"}})
		out = OpenCodeBridge._parse_json_stream(stream)
		assert out["text"] == "x"
		assert out["session_id"] == ""

	def test_first_step_start_wins(self):
		stream = "\n".join(
			[
				json.dumps({"type": "step_start", "sessionID": "first"}),
				json.dumps({"type": "step_start", "sessionID": "second"}),
			]
		)
		assert OpenCodeBridge._parse_json_stream(stream)["session_id"] == "first"

	def test_empty_stream(self):
		assert OpenCodeBridge._parse_json_stream("") == {"session_id": "", "text": ""}


# ── Handshake preamble (pure string builder) ──────────────────────────────────
class TestHandshakePreamble:
	def test_wraps_current_message_and_names_tools(self, bridge):
		out = bridge._build_handshake_preamble("¿cómo vas?")
		assert "<current_message>\n¿cómo vas?\n</current_message>" in out
		# OpenCode-native tool names (no mcp_ prefix)
		assert "swarm_orchestrator_api" in out
		assert "bunker_memory_api" in out
		assert "interceptor_rp" in out


# ── Capabilities + arg mapping (pure) ─────────────────────────────────────────
class TestCapabilitiesAndArgs:
	def test_capabilities(self, bridge):
		caps = bridge.get_capabilities()
		assert caps.backend == BackendType.OPENCODE
		assert caps.auto_approve and caps.conversation_resume and caps.mcp_tools

	def test_model_args(self, bridge):
		assert bridge._model_args("flash") == []
		assert bridge._model_args("") == []
		assert bridge._model_args("anthropic/claude-opus") == ["-m", "anthropic/claude-opus"]
		assert bridge._model_args("opus") == ["-m", "anthropic/opus"]

	def test_effort_args(self, bridge):
		assert bridge._effort_args("low") == ["--variant", "minimal"]
		assert bridge._effort_args("HIGH") == ["--variant", "high"]
		assert bridge._effort_args("medium") == []
		assert bridge._effort_args(None) == []


# ── Scribe relay (temp sqlite) ────────────────────────────────────────────────
class TestScribeRelay:
	def test_writes_interaction_and_migrates_model(self, bridge, tmp_path):
		with patch("red_pill.swarm.bridges.opencode.get_db_dir", return_value=tmp_path):
			# Pre-create the table WITHOUT the model column to exercise the migration.
			conn = sqlite3.connect(str(tmp_path / "bunker.db"))
			conn.execute(
				"CREATE TABLE interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_prompt TEXT, agent_response TEXT, timestamp DATETIME)"
			)
			conn.commit()
			conn.close()

			bridge._scribe_relay("prompt-x", "response-y", model="opus")

			conn = sqlite3.connect(str(tmp_path / "bunker.db"))
			cols = [r[1] for r in conn.execute("PRAGMA table_info(interactions)").fetchall()]
			assert "model" in cols  # self-healing migration ran
			row = conn.execute("SELECT user_prompt, agent_response, model FROM interactions").fetchone()
			conn.close()
			assert row == ("prompt-x", "response-y", "opus")

	def test_truncates_long_fields(self, bridge, tmp_path):
		with patch("red_pill.swarm.bridges.opencode.get_db_dir", return_value=tmp_path):
			conn = sqlite3.connect(str(tmp_path / "bunker.db"))
			conn.execute(
				"CREATE TABLE interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_prompt TEXT, agent_response TEXT, timestamp DATETIME, model TEXT)"
			)
			conn.commit()
			conn.close()
			bridge._scribe_relay("p" * 5000, "r" * 9000, model=None)
			conn = sqlite3.connect(str(tmp_path / "bunker.db"))
			p, r = conn.execute("SELECT user_prompt, agent_response FROM interactions").fetchone()
			conn.close()
			assert len(p) == 2000 and len(r) == 5000

	def test_non_fatal_on_error(self, bridge):
		with patch("red_pill.swarm.bridges.opencode.get_db_dir", return_value=Path("/nonexistent/dir/xyz")):
			# Must not raise even if the DB path is unwritable.
			bridge._scribe_relay("p", "r")


# ── prompt() / continue_conversation() round-trips (mock _run_opencode) ────────
class TestPromptRoundTrip:
	def test_prompt_success_calls_scribe(self, bridge):
		with (
			patch.object(bridge, "_run_opencode", return_value={"session_id": "s1", "text": "answer"}),
			patch.object(bridge, "_scribe_relay") as scribe,
		):
			bridge._scribe_plugin = False
			res = bridge.prompt("hi", model="opus")
		assert res.conversation_id == "s1"
		assert res.response == "answer"
		scribe.assert_called_once()

	def test_prompt_skips_scribe_when_plugin_enabled(self, bridge):
		with (
			patch.object(bridge, "_run_opencode", return_value={"session_id": "s1", "text": "a"}),
			patch.object(bridge, "_scribe_relay") as scribe,
		):
			bridge._scribe_plugin = True
			bridge.prompt("hi")
		scribe.assert_not_called()

	def test_prompt_empty_response_is_error(self, bridge):
		with patch.object(bridge, "_run_opencode", return_value={"session_id": "s1", "text": ""}):
			res = bridge.prompt("hi")
		assert res.response == ""
		assert res.error and "empty" in res.error.lower()

	def test_prompt_run_failure_returns_error_result(self, bridge):
		with patch.object(bridge, "_run_opencode", side_effect=RuntimeError("opencode boom")):
			res = bridge.prompt("hi")
		assert res.error == "opencode boom"

	def test_continue_without_id_falls_back_to_prompt(self, bridge):
		with patch.object(bridge, "prompt", return_value="SENTINEL") as p:
			out = bridge.continue_conversation("hi", conversation_id="")
		assert out == "SENTINEL"
		p.assert_called_once()

	def test_continue_with_id(self, bridge):
		with (
			patch.object(bridge, "_run_opencode", return_value={"session_id": "s2", "text": "resumed"}),
			patch.object(bridge, "_scribe_relay"),
		):
			bridge._scribe_plugin = False
			res = bridge.continue_conversation("more", conversation_id="s2")
		assert res.response == "resumed"


# ── _run_opencode (mock subprocess) ───────────────────────────────────────────
class TestRunOpencode:
	def test_parses_stdout(self, bridge):
		fake = MagicMock(returncode=0, stdout=json.dumps({"type": "text", "part": {"text": "ok"}}), stderr="")
		with patch("subprocess.run", return_value=fake):
			out = bridge._run_opencode(["hi"], timeout=5)
		assert out["text"] == "ok"

	def test_nonzero_returncode_raises(self, bridge):
		fake = MagicMock(returncode=2, stdout="", stderr="bad")
		with patch("subprocess.run", return_value=fake):
			with pytest.raises(RuntimeError):
				bridge._run_opencode(["hi"], timeout=5)


# ── health_check ──────────────────────────────────────────────────────────────
class TestHealthCheck:
	def test_ok(self, bridge):
		good = MagicMock()
		good.ok = True
		good.response = "OK"
		with patch.object(bridge, "prompt", return_value=good):
			assert bridge.health_check() is True

	def test_failure_swallowed(self, bridge):
		with patch.object(bridge, "prompt", side_effect=RuntimeError("down")):
			assert bridge.health_check() is False
