"""
Tests for the execution-bridge fallback cascade (Telegram/inbox worker).

Covers:
  - BridgeTarget pydantic validation (config layer)
  - TELEGRAM_BRIDGE_CASCADE parsing (list + JSON string from env)
  - CascadeBridge.prompt() semantics: first-with-quota wins, empty → raise,
	all-fail → raise with per-target errors, backend-unavailable is skipped

All bridge backends are mocked — no CLI, network, or LLM required.
"""

import json
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from red_pill.config import BridgeTarget, RedPillConfig
from red_pill.swarm.bridges import BackendType, BridgeCapabilities, ConversationResult
from red_pill.swarm.bridges.cascade import AllModelsExhausted, CascadeBridge, NoModelsConfigured


class _FakeBridge:
	"""Minimal AgentBridge stand-in that records how many times it was called."""

	def __init__(self, ok=True, error=None, response="ok-response"):
		self._ok = ok
		self._error = error
		self._response = response
		self.calls = 0

	def prompt(self, text, *, model="flash", effort=None, cwd=None, timeout=300):
		self.calls += 1
		self.last_model = model
		self.last_effort = effort
		self.last_timeout = timeout
		if self._ok:
			return ConversationResult(conversation_id="conv", response=self._response, model=model)
		return ConversationResult(conversation_id="", response="", error=self._error or "boom")

	def get_capabilities(self):
		return BridgeCapabilities(backend=BackendType.CLAUDE)

	def continue_conversation(self, text, *, conversation_id="", previous_response_len=0, timeout=300):
		self.calls += 1
		return ConversationResult(conversation_id=conversation_id or "conv", response="continued")

	def health_check(self):
		return self._ok


def _targets(*specs):
	return [BridgeTarget(**s) for s in specs]


class TestBridgeTarget:
	def test_valid_full(self):
		t = BridgeTarget(backend="claude", model="opus", effort="high")
		assert t.backend == "claude" and t.model == "opus" and t.effort == "high"

	def test_defaults(self):
		t = BridgeTarget(backend="agy")
		assert t.model is None and t.effort is None

	def test_rejects_unknown_backend(self):
		with pytest.raises(ValidationError):
			BridgeTarget(backend="gpt4")

	def test_rejects_unknown_effort(self):
		with pytest.raises(ValidationError):
			BridgeTarget(backend="claude", effort="ultra")

	def test_timeout_field_optional(self):
		t = BridgeTarget(backend="claude", model="opus", timeout=300)
		assert t.timeout == 300

	def test_timeout_defaults_none(self):
		t = BridgeTarget(backend="claude")
		assert t.timeout is None


class TestCascadeConfigParsing:
	def test_default_is_empty(self, monkeypatch):
		# Isolate from the operator's real environment: RedPillConfig is a
		# BaseSettings that reads both process env and the config-dir .env file,
		# so a populated cascade on the host machine would leak into the default.
		for var in ("TELEGRAM_BRIDGE_CASCADE", "AWAKENING_BRIDGE_CASCADE", "DEFAULT_MINION_BRIDGE_CASCADE"):
			monkeypatch.delenv(var, raising=False)
		cfg = RedPillConfig(_env_file=None)
		assert cfg.TELEGRAM_BRIDGE_CASCADE == []
		assert cfg.AWAKENING_BRIDGE_CASCADE == []
		assert cfg.DEFAULT_MINION_BRIDGE_CASCADE == []

	def test_list_of_dicts_coerced(self):
		cfg = RedPillConfig(TELEGRAM_BRIDGE_CASCADE=[{"backend": "claude", "model": "opus", "effort": "high"}])
		assert len(cfg.TELEGRAM_BRIDGE_CASCADE) == 1
		assert isinstance(cfg.TELEGRAM_BRIDGE_CASCADE[0], BridgeTarget)
		assert cfg.TELEGRAM_BRIDGE_CASCADE[0].backend == "claude"

	def test_json_string_from_env(self):
		raw = json.dumps([{"backend": "claude", "model": "opus", "effort": "high"}, {"backend": "agy", "model": "pro"}])
		with patch.dict(os.environ, {"TELEGRAM_BRIDGE_CASCADE": raw}):
			cfg = RedPillConfig()
		assert [t.backend for t in cfg.TELEGRAM_BRIDGE_CASCADE] == ["claude", "agy"]


class TestCascadeBridge:
	def test_empty_raises_no_models(self):
		bridge = CascadeBridge([])
		with pytest.raises(NoModelsConfigured):
			bridge.prompt("hello")

	def test_first_ok_wins_and_short_circuits(self):
		first = _FakeBridge(ok=True, response="from-claude")
		second = _FakeBridge(ok=True, response="from-agy")
		built = {"claude": first, "agy": second}
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: built[b]):
			res = CascadeBridge(_targets({"backend": "claude", "model": "opus", "effort": "high"}, {"backend": "agy"})).prompt("hi")
		assert res.ok and res.response == "from-claude"
		assert first.calls == 1 and second.calls == 0
		# per-target model/effort propagated
		assert first.last_model == "opus" and first.last_effort == "high"

	def test_falls_through_to_second_on_failure(self):
		first = _FakeBridge(ok=False, error="quota exhausted")
		second = _FakeBridge(ok=True, response="from-agy")
		built = {"claude": first, "agy": second}
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: built[b]):
			res = CascadeBridge(_targets({"backend": "claude", "model": "opus"}, {"backend": "agy", "model": "pro"})).prompt("hi")
		assert res.ok and res.response == "from-agy"
		assert first.calls == 1 and second.calls == 1

	def test_all_fail_raises_with_errors(self):
		first = _FakeBridge(ok=False, error="quota exhausted")
		second = _FakeBridge(ok=False, error="rate limited")
		built = {"claude": first, "agy": second}
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: built[b]):
			with pytest.raises(AllModelsExhausted) as exc:
				CascadeBridge(_targets({"backend": "claude"}, {"backend": "agy"})).prompt("hi")
		errors = exc.value.errors
		assert len(errors) == 2
		assert errors[0][1] == "quota exhausted" and errors[1][1] == "rate limited"

	def test_backend_unavailable_is_skipped(self):
		ok_bridge = _FakeBridge(ok=True, response="from-local")

		def _build(backend):
			if backend == "claude":
				raise RuntimeError("claude CLI not found")
			return ok_bridge

		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=_build):
			res = CascadeBridge(_targets({"backend": "claude"}, {"backend": "local"})).prompt("hi")
		assert res.ok and res.response == "from-local"
		assert ok_bridge.calls == 1

	def test_per_target_timeout_overrides_method(self):
		# Target declares timeout=45 → the bridge must be called with 45, NOT the
		# method default (300) NOR the caller's timeout (200).
		fb = _FakeBridge(ok=True)
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: fb):
			CascadeBridge(_targets({"backend": "claude", "timeout": 45})).prompt("hi", timeout=200)
		assert fb.last_timeout == 45

	def test_method_timeout_used_when_target_has_none(self):
		# Target without timeout → falls back to the caller's method timeout.
		fb = _FakeBridge(ok=True)
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: fb):
			CascadeBridge(_targets({"backend": "claude"})).prompt("hi", timeout=200)
		assert fb.last_timeout == 200

	def test_timeout_flows_through_fallback_targets(self):
		# Each target gets its own effective timeout (per-target or method).
		first = _FakeBridge(ok=False, error="boom")
		second = _FakeBridge(ok=True)
		built = {"claude": first, "agy": second}
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: built[b]):
			res = CascadeBridge(
				_targets({"backend": "claude", "timeout": 10}, {"backend": "agy", "timeout": 20})
			).prompt("hi", timeout=30)
		assert res.ok
		assert first.last_timeout == 10 and second.last_timeout == 20


class TestCascadeDelegation:
	def test_get_capabilities_uses_primary(self):
		fb = _FakeBridge(ok=True)
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: fb):
			caps = CascadeBridge(_targets({"backend": "claude"})).get_capabilities()
		assert caps.backend == BackendType.CLAUDE

	def test_get_capabilities_defaults_grpc_when_none_build(self):
		def _boom(backend):
			raise RuntimeError("nope")

		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=_boom):
			caps = CascadeBridge(_targets({"backend": "claude"})).get_capabilities()
		assert caps.backend == BackendType.GRPC

	def test_continue_conversation_delegates(self):
		fb = _FakeBridge(ok=True)
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: fb):
			res = CascadeBridge(_targets({"backend": "claude"})).continue_conversation("hi", conversation_id="c1")
		assert res.response == "continued" and res.conversation_id == "c1"

	def test_continue_conversation_raises_when_no_primary(self):
		def _boom(backend):
			raise RuntimeError("nope")

		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=_boom):
			with pytest.raises(AllModelsExhausted):
				CascadeBridge(_targets({"backend": "claude"})).continue_conversation("hi")

	def test_health_check_true_if_any_reachable(self):
		built = {"claude": _FakeBridge(ok=False), "agy": _FakeBridge(ok=True)}
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: built[b]):
			assert CascadeBridge(_targets({"backend": "claude"}, {"backend": "agy"})).health_check() is True

	def test_health_check_false_if_none(self):
		with patch("red_pill.swarm.bridges.factory.create_bridge", side_effect=lambda b: _FakeBridge(ok=False)):
			assert CascadeBridge(_targets({"backend": "claude"})).health_check() is False


class TestRegressionGuardD3:
	"""Guard de regresión §2C/D3: el primario de TELEGRAM_BRIDGE_CASCADE del .env
	real debe llevar un timeout generoso (300s) para que el default de método de
	D3 (120s) no se convierta en un kill agresivo del primario (D14)."""

	def _operator_env_path(self) -> str:
		from red_pill.config import get_config_dir

		return os.path.join(get_config_dir(), ".env")

	def test_operator_env_primario_lleva_timeout_generoso(self):
		env_path = self._operator_env_path()
		if not os.path.exists(env_path):
			pytest.skip(f"Operator .env not present at {env_path}")

		with open(env_path, "r", encoding="utf-8") as f:
			content = f.read()

		# Locate the TELEGRAM_BRIDGE_CASCADE line
		match = None
		for line in content.splitlines():
			if line.strip().startswith("TELEGRAM_BRIDGE_CASCADE"):
				match = line
				break
		if not match:
			pytest.skip("TELEGRAM_BRIDGE_CASCADE not set in operator .env")

		# Parse the JSON value (strip var name and optional quotes)
		raw = match.split("=", 1)[1].strip().strip("'").strip('"')
		targets = json.loads(raw)
		assert targets, "cascade must not be empty"
		primario = targets[0]
		assert primario.get("timeout") is not None, (
			f"Primario {primario.get('model')} sin timeout en .env real → con "
			"TELEGRAM_INLINE_TIMEOUT=120 (D3) sería un kill agresivo (D14). "
			"Añade \"timeout\":300 al primario."
		)
		assert primario["timeout"] >= 300, (
			f"Primario timeout={primario['timeout']} < 300s — no es generoso (D14)."
		)
