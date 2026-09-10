"""Tests del PiBridge (backend pi-coding-agent para minions).

La integración real requiere proveedor/modelo configurados en Pi, así que se
testea la construcción de comandos, el parseo del stream JSON de `pi --mode
json` y la semántica prompt/continue con `subprocess.run` mockeado. No toca
`~/.pi` del operador (HOME aislado en el run de la suite).
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from red_pill.swarm.bridges.base import BackendType
from red_pill.swarm.bridges.pi import PiBridge, _text_of


def _sample_stream():
	return "\n".join(
		[
			json.dumps({"type": "session", "version": 3, "id": "abc123def", "timestamp": "2026-09-10T10:00:00.000Z", "cwd": "/tmp"}),
			json.dumps({"type": "agent_start"}),
			json.dumps({"type": "turn_start"}),
			json.dumps({"type": "message_start", "message": {"role": "assistant", "content": []}}),
			json.dumps({"type": "message_update", "usage": {}, "assistantMessageEvent": {"type": "text_delta", "delta": "Hello"}}),
			json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello there"}]}}),
			json.dumps({"type": "turn_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello there"}]}}),
			json.dumps({"type": "agent_end", "messages": []}),
		]
	) + "\n"


@pytest.fixture()
def bridge():
	b = PiBridge(pi_path="/fake/bin/pi")
	b._extension_present = True  # el harness extension hace el scribe → no doble cola
	return b


def test_capabilities(bridge):
	caps = bridge.get_capabilities()
	assert caps.backend == BackendType.PI
	assert caps.auto_approve is True
	assert caps.ephemeral_mode is False  # sesiones persistidas → chronicle
	assert caps.conversation_resume is True
	assert caps.mcp_tools is False  # Pi no soporta MCP


def test_model_args():
	assert PiBridge._model_args("flash") == []
	assert PiBridge._model_args("") == []
	assert PiBridge._model_args("kimi-k2.6") == ["--model", "kimi-k2.6"]
	assert PiBridge._model_args("opencode/kimi") == ["--model", "opencode/kimi"]


def test_effort_args():
	assert PiBridge._effort_args("low") == ["--thinking", "low"]
	assert PiBridge._effort_args("high") == ["--thinking", "high"]
	assert PiBridge._effort_args("medium") == []
	assert PiBridge._effort_args(None) == []


def test_parse_json_stream(bridge):
	data = bridge._parse_json_stream(_sample_stream())
	assert data["session_id"] == "abc123def"
	assert data["text"] == "Hello there"


def test_text_of_blocks():
	assert _text_of("hola") == "hola"
	assert _text_of([{"type": "text", "text": "a"}, {"type": "thinking", "thinking": "x"}, {"type": "text", "text": "b"}]) == "a\nb"
	assert _text_of([{"type": "toolCall", "name": "read"}]) == ""


def test_prompt_builds_command_and_returns_response(bridge):
	with mock.patch("subprocess.run") as run:
		run.return_value = mock.MagicMock(returncode=0, stdout=_sample_stream(), stderr="")
		result = bridge.prompt("haz algo", model="kimi-k2.6", effort="high", cwd="/tmp/ws", timeout=120)

	cmd = run.call_args.args[0]
	assert cmd[0] == "/fake/bin/pi"
	assert "--mode" in cmd and "json" in cmd
	assert "--approve" in cmd
	assert "--model" in cmd and "kimi-k2.6" in cmd
	assert "--thinking" in cmd and "high" in cmd
	assert cmd[-1] == "haz algo"
	# cwd propagado
	assert run.call_args.kwargs["cwd"] == "/tmp/ws"

	assert result.ok
	assert result.response == "Hello there"
	assert result.conversation_id == "abc123def"


def test_prompt_empty_response_marks_error(bridge):
	stream = '{"type":"session","version":3,"id":"s1","timestamp":"t","cwd":"/"}\n'
	with mock.patch("subprocess.run") as run:
		run.return_value = mock.MagicMock(returncode=0, stdout=stream, stderr="")
		result = bridge.prompt("noop")
	assert not result.ok
	assert "empty" in result.error


def test_prompt_nonzero_exit_marks_error(bridge):
	with mock.patch("subprocess.run") as run:
		run.return_value = mock.MagicMock(returncode=2, stdout="", stderr="boom")
		result = bridge.prompt("x")
	assert not result.ok
	assert "boom" in result.error


def test_continue_conversation_uses_session(bridge):
	stream = '{"type":"session","version":3,"id":"abc123def","timestamp":"t","cwd":"/"}\n{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"sigo"}]}}\n'
	with mock.patch("subprocess.run") as run:
		run.return_value = mock.MagicMock(returncode=0, stdout=stream, stderr="")
		result = bridge.continue_conversation("sigue", conversation_id="abc123def")
	cmd = run.call_args.args[0]
	assert "--session" in cmd and "abc123def" in cmd
	assert result.ok and result.response == "sigo"
	assert result.conversation_id == "abc123def"


def test_continue_without_id_falls_back_to_prompt(bridge):
	with mock.patch.object(bridge, "prompt", return_value=mock.MagicMock(ok=True, response="ok", conversation_id="")):
		result = bridge.continue_conversation("x")
	assert result.ok


def test_factory_registers_pi(monkeypatch):
	import red_pill.swarm.bridges.pi as pi_mod
	from red_pill.swarm.bridges.factory import create_bridge

	monkeypatch.setattr(pi_mod, "_resolve_pi_bin", lambda: "/fake/bin/pi")
	bridge = create_bridge("pi")
	assert isinstance(bridge, PiBridge)
