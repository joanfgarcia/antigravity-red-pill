"""
Unit tests for the agent-execution bridges and their factory.

Covers ClaudeBridge (subprocess mocked), LocalBridge (provider injected), and the
factory routing (create_bridge / create_cascade_bridge / create_extraction_bridge /
preflight_check). No real CLI, network, model, or IDE is required.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from red_pill.swarm.bridges import BackendType
from red_pill.swarm.bridges.claude import ClaudeBridge
from red_pill.swarm.bridges.local import LocalBridge


def _completed(returncode=0, stdout="", stderr=""):
	m = MagicMock()
	m.returncode = returncode
	m.stdout = stdout
	m.stderr = stderr
	return m


# ───────────────────────────── LocalBridge ─────────────────────────────


class TestLocalBridge:
	def test_capabilities(self):
		caps = LocalBridge().get_capabilities()
		assert caps.backend == BackendType.LOCAL
		assert caps.mcp_tools is False and caps.conversation_resume is False

	def test_prompt_uses_injected_provider(self):
		provider = MagicMock()
		provider.generate.return_value = "local answer"
		res = LocalBridge(provider=provider, model_profile="samantha").prompt("hola")
		assert res.ok and res.response == "local answer" and res.model == "samantha"
		provider.generate.assert_called_once()

	def test_prompt_provider_error_is_captured(self):
		provider = MagicMock()
		provider.generate.side_effect = RuntimeError("model down")
		res = LocalBridge(provider=provider).prompt("hola")
		assert not res.ok and "model down" in res.error

	def test_continue_conversation_delegates_to_prompt(self):
		provider = MagicMock()
		provider.generate.return_value = "answer"
		res = LocalBridge(provider=provider).continue_conversation("hi", conversation_id="x")
		assert res.ok and res.response == "answer"

	def test_health_check_true_with_provider(self):
		assert LocalBridge(provider=MagicMock()).health_check() is True

	def test_health_check_false_when_no_provider(self):
		with patch("red_pill.core.providers.ProviderRegistry.get_inference_provider", return_value=None):
			assert LocalBridge().health_check() is False


# ───────────────────────────── ClaudeBridge ────────────────────────────


class TestClaudeBridgeConstruction:
	def test_raises_when_cli_missing(self):
		with patch("shutil.which", return_value=None):
			with pytest.raises(RuntimeError):
				ClaudeBridge()

	def test_uses_explicit_path(self):
		assert ClaudeBridge(claude_path="/usr/bin/claude")._claude_path == "/usr/bin/claude"

	def test_capabilities(self):
		caps = ClaudeBridge(claude_path="/usr/bin/claude").get_capabilities()
		assert caps.backend == BackendType.CLAUDE
		assert caps.auto_approve and caps.mcp_tools

	def test_model_and_effort_args(self):
		b = ClaudeBridge(claude_path="/usr/bin/claude")
		assert b._model_args("flash") == []
		assert b._model_args("opus") == ["--model", "opus"]
		assert b._effort_args("high") == ["--effort", "high"]
		assert b._effort_args(None) == []
		assert b._effort_args("ultra") == []


class TestClaudeBridgePrompt:
	def _bridge(self):
		return ClaudeBridge(claude_path="/usr/bin/claude")

	def test_prompt_success(self):
		out = json.dumps({"session_id": "s1", "result": "hello world"})
		with patch("subprocess.run", return_value=_completed(0, out)):
			res = self._bridge().prompt("hi", model="opus", effort="high")
		assert res.ok and res.response == "hello world" and res.conversation_id == "s1"

	def test_prompt_is_error_flag(self):
		out = json.dumps({"session_id": "s1", "is_error": True, "result": "usage limit reached"})
		with patch("subprocess.run", return_value=_completed(0, out)):
			res = self._bridge().prompt("hi")
		assert not res.ok and "usage limit reached" in res.error

	def test_prompt_nonzero_returncode(self):
		with patch("subprocess.run", return_value=_completed(1, "", "boom")):
			res = self._bridge().prompt("hi")
		assert not res.ok and "boom" in res.error

	def test_prompt_timeout(self):
		with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
			res = self._bridge().prompt("hi", timeout=5)
		assert not res.ok and "timed out" in res.error

	def test_prompt_empty_output(self):
		with patch("subprocess.run", return_value=_completed(0, "")):
			res = self._bridge().prompt("hi")
		assert not res.ok and "empty" in res.error

	def test_prompt_non_json_output(self):
		with patch("subprocess.run", return_value=_completed(0, "not json")):
			res = self._bridge().prompt("hi")
		assert not res.ok and "not JSON" in res.error

	def test_continue_conversation_with_id(self):
		out = json.dumps({"session_id": "s2", "result": "more"})
		with patch("subprocess.run", return_value=_completed(0, out)):
			res = self._bridge().continue_conversation("again", conversation_id="s1")
		assert res.ok and res.response == "more" and res.conversation_id == "s2"

	def test_continue_conversation_without_id_falls_back_to_prompt(self):
		out = json.dumps({"session_id": "s3", "result": "fresh"})
		with patch("subprocess.run", return_value=_completed(0, out)):
			res = self._bridge().continue_conversation("again", conversation_id="")
		assert res.ok and res.response == "fresh"

	def test_health_check_true_on_ok(self):
		out = json.dumps({"session_id": "s1", "result": "OK"})
		with patch("subprocess.run", return_value=_completed(0, out)):
			assert self._bridge().health_check() is True

	def test_health_check_false_on_error(self):
		with patch("subprocess.run", return_value=_completed(1, "", "fail")):
			assert self._bridge().health_check() is False


# ───────────────────────────── Factory ─────────────────────────────────


class TestFactory:
	def test_create_bridge_claude(self):
		from red_pill.swarm.bridges import create_bridge

		with patch("red_pill.swarm.bridges.claude.ClaudeBridge") as MC:
			create_bridge("claude")
		MC.assert_called_once()

	def test_create_bridge_local(self):
		from red_pill.swarm.bridges import create_bridge

		with patch("red_pill.swarm.bridges.local.LocalBridge") as ML:
			create_bridge("local")
		ML.assert_called_once()

	def test_create_bridge_auto_prefers_agy_when_available(self):
		from red_pill.swarm.bridges import create_bridge

		with (
			patch("shutil.which", return_value="/usr/bin/agy"),
			patch("red_pill.plugins.antigravity_ide.agy_bridge.AgyBridge") as MA,
		):
			create_bridge("auto")
		MA.assert_called_once()

	def test_create_bridge_auto_falls_back_to_grpc(self):
		from red_pill.swarm.bridges import create_bridge

		with (
			patch("shutil.which", return_value=None),
			patch("red_pill.plugins.antigravity_ide.grpc_bridge.GrpcBridge") as MG,
		):
			create_bridge("auto")
		MG.assert_called_once()

	def test_create_extraction_bridge_is_grpc(self):
		from red_pill.swarm.bridges import create_extraction_bridge

		with patch("red_pill.plugins.antigravity_ide.grpc_bridge.GrpcBridge") as MG:
			create_extraction_bridge()
		MG.assert_called_once()

	def test_create_cascade_bridge_empty_falls_back_to_single(self):
		import red_pill.config as cfg
		from red_pill.swarm.bridges import create_cascade_bridge

		cfg_obj = cfg.get_config()
		with (
			patch.object(cfg_obj, "TELEGRAM_BRIDGE_CASCADE", []),
			patch("red_pill.config.get_config", return_value=cfg_obj),
			patch("red_pill.swarm.bridges.factory.create_bridge") as CB,
		):
			create_cascade_bridge()
		CB.assert_called_once_with()

	def test_create_cascade_bridge_uses_cascade_when_configured(self):
		import red_pill.config as cfg
		from red_pill.config import BridgeTarget
		from red_pill.swarm.bridges import create_cascade_bridge
		from red_pill.swarm.bridges.cascade import CascadeBridge

		cfg_obj = cfg.get_config()
		targets = [BridgeTarget(backend="claude", model="opus", effort="high")]
		with (
			patch.object(cfg_obj, "TELEGRAM_BRIDGE_CASCADE", targets),
			patch("red_pill.config.get_config", return_value=cfg_obj),
		):
			bridge = create_cascade_bridge()
		assert isinstance(bridge, CascadeBridge)

	def test_preflight_ready_with_agy(self):
		from red_pill.swarm.bridges import preflight_check

		with (
			patch("shutil.which", return_value="/usr/bin/agy"),
			patch("subprocess.run", return_value=_completed(0, "agy 1.0")),
			patch("red_pill.utils.antigravity_history.discovery.discover_language_servers", return_value=["ls1"]),
		):
			result = preflight_check()
		assert result["ready"] is True and result["backend"] == "agy"

	def test_preflight_errors_without_agy(self):
		from red_pill.swarm.bridges import preflight_check

		with (
			patch("shutil.which", return_value=None),
			patch("red_pill.utils.antigravity_history.discovery.discover_language_servers", return_value=[]),
		):
			result = preflight_check()
		assert result["ready"] is False and result["errors"]
