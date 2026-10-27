"""Tests for OpenCodeBridge (swarm/bridges/opencode.py).

The bridge shells out to the `opencode` CLI, but its logic — stream parsing,
handshake preamble, scribe relay, model/effort arg mapping, capabilities, and the
prompt/continue round-trips — is pure or mockable. `opencode` need not be
installed: we pass an explicit binary path to bypass the PATH check and mock
`_run_opencode`/`subprocess.run`.
"""

import json
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

	def test_model_effort_args(self, bridge):
		# V2 embebe la variante en la referencia del modelo (#variant): no existe
		# `--variant` como flag propia.
		assert bridge._model_effort_args("anthropic/claude-opus", "high") == ["-m", "anthropic/claude-opus#high"]
		assert bridge._model_effort_args("anthropic/claude-opus", "low") == ["-m", "anthropic/claude-opus#minimal"]
		assert bridge._model_effort_args("anthropic/claude-opus", "medium") == ["-m", "anthropic/claude-opus"]
		# Sin modelo no hay dónde embeberla: se omite.
		assert bridge._model_effort_args("flash", "high") == []


# ── Scribe relay (temp sqlite) ────────────────────────────────────────────────
class TestScribeRelay:
	def test_queues_the_turn_for_ingestion(self, bridge, tmp_path):
		"""El bridge headless captura hacia LA cola, no hacia una tabla propia."""
		from red_pill.core.queue_manager import MemoryQueueManager

		queue = MemoryQueueManager(db_path=str(tmp_path / "bunker_queue.db"))
		with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=queue):
			bridge._scribe_relay("prompt-x", "response-y", model="opus")

		item = queue.dequeue_pending(limit=1)[0]
		assert (item["prompt"], item["response"], item["model"]) == ("prompt-x", "response-y", "opus")
		assert item["originator"] == "opencode"  # procedencia, que la tabla vieja tiraba

	def test_keeps_the_full_text(self, bridge, tmp_path):
		"""Truncar aquí mutilaría el engrama; recortar ruido es cosa del worker."""
		from red_pill.core.queue_manager import MemoryQueueManager

		queue = MemoryQueueManager(db_path=str(tmp_path / "bunker_queue.db"))
		with patch("red_pill.core.queue_manager.MemoryQueueManager", return_value=queue):
			bridge._scribe_relay("p" * 5000, "r" * 9000, model=None)

		item = queue.dequeue_pending(limit=1)[0]
		assert (len(item["prompt"]), len(item["response"])) == (5000, 9000)

	def test_non_fatal_on_error(self, bridge):
		with patch("red_pill.core.queue_manager.MemoryQueueManager", side_effect=RuntimeError("queue down")):
			# Capturar no puede tumbar la respuesta al operador.
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

	def test_cwd_is_the_only_workspace_source(self, bridge, tmp_path):
		"""V2 no tiene `--dir`: el workspace de la sesión ES el cwd del subproceso.

		Regresión del job `09192498` (2026-10-27): pasar `--dir` hacía fallar el
		CLI con `Unrecognized flag: --dir in command opencode run`.
		"""
		fake = MagicMock(returncode=0, stdout="", stderr="")
		with patch("subprocess.run", return_value=fake) as run:
			bridge._run_opencode(["hi"], timeout=5, cwd=str(tmp_path))
		cmd = run.call_args.args[0]
		assert run.call_args.kwargs["cwd"] == str(tmp_path)
		assert "--dir" not in cmd
		assert not any(str(a) == str(tmp_path) for a in cmd)

	def test_nonzero_returncode_raises(self, bridge):
		fake = MagicMock(returncode=2, stdout="", stderr="bad")
		with patch("subprocess.run", return_value=fake):
			with pytest.raises(RuntimeError, match="bad"):
				bridge._run_opencode(["hi"], timeout=5)

	def test_nonzero_returncode_falls_back_to_stdout(self, bridge):
		"""opencode reporta errores fatales por stdout: sin fallback el error_log
		quedaba en `... (rc=1): `, imposible de diagnosticar."""
		fake = MagicMock(returncode=1, stdout="Error: model not found\n", stderr="")
		with patch("subprocess.run", return_value=fake):
			with pytest.raises(RuntimeError, match="model not found"):
				bridge._run_opencode(["hi"], timeout=5)

	def test_failure_detail_prefers_stderr_and_truncates(self, bridge):
		assert bridge._failure_detail("boom", "ignored") == "boom"
		assert bridge._failure_detail("", "tail") == "tail"
		assert bridge._failure_detail("", "") == "<sin salida en stderr ni stdout>"
		assert bridge._failure_detail("", "x" * 500, limit=10) == "x" * 10

	def test_disables_plugin_when_relay_captures(self, bridge):
		fake = MagicMock(returncode=0, stdout="", stderr="")
		bridge._scribe_plugin = False
		with patch("subprocess.run", return_value=fake) as run:
			bridge._run_opencode(["hi"], timeout=5)
		assert run.call_args.kwargs["env"]["REDPILL_SCRIBE_DISABLE"] == "1"

	def test_keeps_plugin_when_it_captures(self, bridge):
		fake = MagicMock(returncode=0, stdout="", stderr="")
		bridge._scribe_plugin = True
		with patch("subprocess.run", return_value=fake) as run:
			bridge._run_opencode(["hi"], timeout=5)
		env = run.call_args.kwargs["env"]
		assert env["REDPILL_TURN_JOURNAL_DISABLE"] == "1"
		assert "REDPILL_SCRIBE_DISABLE" not in env

	def test_disables_plugin_for_telegram_origin(self):
		tg = OpenCodeBridge(opencode_path="/bin/true", origin="telegram")
		tg._scribe_plugin = True
		fake = MagicMock(returncode=0, stdout="", stderr="")
		with patch("subprocess.run", return_value=fake) as run:
			tg._run_opencode(["hi"], timeout=5)
		assert run.call_args.kwargs["env"]["REDPILL_SCRIBE_DISABLE"] == "1"

	def test_attached_uses_server_flag(self, bridge):
		fake = MagicMock(returncode=0, stdout="", stderr="")
		bridge._server_url = "http://127.0.0.1:4096"
		with patch("subprocess.run", return_value=fake) as run:
			bridge._run_opencode(["hi"], timeout=5)
		cmd = run.call_args.args[0]
		assert "--server" in cmd and "--standalone" not in cmd
		# `--attach` es de V1 y ya no existe en el CLI.
		assert "--attach" not in cmd

	def test_direct_uses_standalone(self, bridge):
		fake = MagicMock(returncode=0, stdout="", stderr="")
		bridge._server_url = ""
		with patch("subprocess.run", return_value=fake) as run:
			bridge._run_opencode(["hi"], timeout=5)
		assert "--standalone" in run.call_args.args[0]

	def test_no_v1_flags_ever(self, bridge):
		"""Blindaje V2+: ninguna bandera retirada puede reaparecer."""
		fake = MagicMock(returncode=0, stdout="", stderr="")
		for server in ("", "http://127.0.0.1:4096"):
			bridge._server_url = server
			with patch("subprocess.run", return_value=fake) as run:
				bridge._run_opencode(["hi"], timeout=5)
			cmd = run.call_args.args[0]
			for banned in ("--dir", "--attach", "--variant"):
				assert banned not in cmd, f"{banned} reapareció en {cmd}"


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
