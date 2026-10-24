"""MiniLocalBridge + factory + agentic job plumbing (no live models)."""

import json
from types import SimpleNamespace

import pytest

from red_pill.jobs.drivers.agentic import AgenticJobDriver
from red_pill.mini.bridge import MiniLocalBridge
from red_pill.mini.tools import WorkspaceTools
from red_pill.swarm.bridges.factory import create_bridge


class BridgeProvider:
	def __init__(self, script):
		self.script = list(script)
		self.calls = []
		self.healthy = True

	def health(self):
		return self.healthy

	def chat(self, messages, **kwargs):
		self.calls.append({"messages": list(messages), **kwargs})
		return self.script.pop(0)


def _tool_call(name, args, call_id="c1"):
	return {
		"role": "assistant",
		"content": None,
		"tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
	}


def _workspace(tmp_path):
	(tmp_path / "calc.py").write_text("def median(values):\n\treturn values[0]\n", encoding="utf-8")
	return WorkspaceTools(str(tmp_path))


def _bridge(tmp_path, script):
	provider = BridgeProvider(script)
	bridge = MiniLocalBridge(
		profile="forge",
		continuity_id="alma-bridge",
		mission_id="mission:bridge",
		workspace=str(tmp_path),
		db_path=str(tmp_path / "session.db"),
		providers={"forge": provider, "loom": BridgeProvider([])},
		toolboxes={"workspace": _workspace(tmp_path)},
	)
	return bridge, provider


def test_bridge_runs_profile_with_tools_and_mirror(tmp_path):
	bridge, provider = _bridge(tmp_path, [_tool_call("read_file", {"path": "calc.py"}), {"role": "assistant", "content": "done"}])
	result = bridge.prompt("read calc.py")
	assert result.ok and result.response == "done"
	assert result.conversation_id == "alma-bridge"
	turns = bridge._session.mirror.read_turns("alma-bridge")
	assert [t["role"] for t in turns] == ["user", "assistant", "tool", "assistant"]
	assert turns[2]["tool_call_id"] == "c1"
	assert "def median" in turns[2]["content"]
	assert "Forge" in provider.calls[0]["messages"][0]["content"]


def test_bridge_continue_uses_mirror_history(tmp_path):
	bridge, provider = _bridge(tmp_path, [{"role": "assistant", "content": "first"}, {"role": "assistant", "content": "second"}])
	assert bridge.prompt("one").response == "first"
	assert bridge.continue_conversation("two").response == "second"
	second_messages = provider.calls[1]["messages"]
	assert any(m.get("content") == "one" for m in second_messages)
	assert any(m.get("content") == "first" for m in second_messages)


def test_bridge_capabilities_and_health(tmp_path):
	bridge, provider = _bridge(tmp_path, [])
	caps = bridge.get_capabilities()
	assert caps.conversation_resume is True
	assert caps.model_selection is False
	assert bridge.health_check() is True
	provider.healthy = False
	assert bridge.health_check() is False


def test_factory_creates_local_mini(tmp_path):
	provider = BridgeProvider([{"role": "assistant", "content": "ok"}])
	bridge = create_bridge(
		"local-mini",
		profile="forge",
		continuity_id="alma-factory",
		mission_id="mission:factory",
		workspace=str(tmp_path),
		db_path=str(tmp_path / "session.db"),
		providers={"forge": provider, "loom": BridgeProvider([])},
		toolboxes={"workspace": _workspace(tmp_path)},
	)
	assert isinstance(bridge, MiniLocalBridge)
	assert bridge.prompt("x").response == "ok"


def test_preflight_rejects_invalid_profile_not_deferral():
	driver = AgenticJobDriver()
	with pytest.raises(ValueError):
		driver.preflight({"backend": "local-mini", "profile": "no-such-profile"})


def test_agentic_job_passes_continuity_and_checkpoints_it(tmp_path):
	driver = AgenticJobDriver()
	seen = {}

	class FakeBridge:
		continuity_id = "alma-job"

		def prompt(self, text, **kwargs):
			return SimpleNamespace(ok=True, response="job done", conversation_id="alma-job", error=None)

	def fake_create(payload):
		seen.update(payload)
		return FakeBridge()

	driver._create_bridge = fake_create  # type: ignore[method-assign]
	outcome = driver.step({"prompt": "do it", "backend": "local-mini"}, {"continuity_id": "alma-from-checkpoint"})
	assert outcome.completed is True
	assert seen["continuity_id"] == "alma-from-checkpoint"
	assert outcome.new_checkpoint["continuity_id"] == "alma-job"
	assert outcome.new_checkpoint["conversation_id"] == "alma-job"
