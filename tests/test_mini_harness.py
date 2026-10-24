"""Unit tests for the local mini harness (Forge/Loom), no live models."""

import json
import sys

import pytest

from red_pill.mini.session import MiniConfig, MiniSession
from red_pill.mini.smoke import PHASE1_TASK, prepare_fixture
from red_pill.mini.tools import TOOL_SCHEMAS, ToolError, WorkspaceTools


class ScriptedProvider:
	def __init__(self, script):
		self.script = list(script)
		self.calls = []

	def chat(self, messages, **kwargs):
		self.calls.append({"messages": list(messages), **kwargs})
		if not self.script:
			raise AssertionError("ScriptedProvider exhausted")
		return self.script.pop(0)


def _tool_call(name, args, call_id="c1"):
	return {
		"role": "assistant",
		"content": None,
		"tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
	}


def _session(tmp_path, forge_script, loom_script=None):
	workspace = tmp_path / "ws"
	workspace.mkdir()
	(workspace / "calc.py").write_text("def median(values):\n\treturn values[0]\n", encoding="utf-8")
	config = MiniConfig(
		workspace=str(workspace),
		continuity_id="alma-mini-test",
		mission_id="mission:mini-test",
		db_path=str(tmp_path / "session.db"),
		affinity=["mission:mini-test"],
	)
	providers = {"forge": ScriptedProvider(forge_script)}
	if loom_script is not None:
		providers["loom"] = ScriptedProvider(loom_script)
	return MiniSession(config, providers), WorkspaceTools(str(workspace)), workspace


class TestWorkspaceTools:
	def test_read_write_edit_and_list(self, tmp_path):
		tools = WorkspaceTools(str(tmp_path))
		(tmp_path / "a.txt").write_text("hello", encoding="utf-8")
		assert tools.read_file("a.txt")["content"] == "hello"
		tools.write_file("sub/b.txt", "world")
		assert (tmp_path / "sub" / "b.txt").read_text() == "world"
		tools.edit_file("a.txt", "hello", "bye")
		assert (tmp_path / "a.txt").read_text() == "bye"
		assert "a.txt" in tools.list_files()["files"]

	def test_path_jail(self, tmp_path):
		(tmp_path / "ws").mkdir()
		tools = WorkspaceTools(str(tmp_path / "ws"))
		with pytest.raises(ToolError):
			tools.read_file("../secret.txt")
		with pytest.raises(ToolError):
			tools.write_file("/etc/passwd", "x")

	def test_edit_requires_unique_match(self, tmp_path):
		(tmp_path / "a.txt").write_text("x x", encoding="utf-8")
		tools = WorkspaceTools(str(tmp_path))
		with pytest.raises(ToolError):
			tools.edit_file("a.txt", "x", "y")

	def test_run_tests(self, tmp_path):
		(tmp_path / "test_ok.py").write_text("def test_ok():\n\tassert True\n", encoding="utf-8")
		tools = WorkspaceTools(str(tmp_path), tests_cmd=[sys.executable, "-m", "pytest", "-q"])
		result = tools.run_tests()
		assert result["ok"] is True
		assert result["exit_code"] == 0


class TestMiniSession:
	def test_tool_loop_appends_canonical_turns(self, tmp_path):
		provider = ScriptedProvider([_tool_call("read_file", {"path": "calc.py"}), {"role": "assistant", "content": "done"}])
		session, tools, _ = _session(tmp_path, [])
		session.providers["forge"] = provider
		result = session.run(
			"forge",
			system_prompt="You are Forge, a local executor.",
			task="read calc.py",
			tools=TOOL_SCHEMAS,
			executor=tools,
		)
		assert result["text"] == "done"
		assert result["tool_calls"] == 1
		turns = session.mirror.read_turns("alma-mini-test")
		assert [t["role"] for t in turns] == ["user", "assistant", "tool", "assistant"]
		assert turns[2]["tool_call_id"] == "c1"
		assert "def median" in turns[2]["content"]
		assert "sovereign_handshake" not in json.dumps(turns)
		assert provider.calls[0]["messages"][0]["role"] == "system"
		assert "Forge" in provider.calls[0]["messages"][0]["content"]
		assert "BUNKER" not in provider.calls[0]["messages"][0]["content"]

	def test_switch_migrates_one_active_leg_and_same_soul(self, tmp_path):
		session, tools, _ = _session(
			tmp_path,
			[{"role": "assistant", "content": "forge done"}],
			[{"role": "assistant", "content": "loom review"}],
		)
		session.run("forge", system_prompt="You are Forge.", task="fix", tools=None)
		session.run("loom", system_prompt="You are Loom.", task="review", tools=None, role="reviewer")
		rows = session.registry.get_by_continuity("alma-mini-test")
		active = [r for r in rows if r.get("ttl_state") != "expired"]
		assert len(active) == 1
		assert active[0]["originator"].startswith("loom:")
		assert all(r["continuity_id"] == "alma-mini-test" for r in rows)
		events = session.registry.fetch_events("mission:mini-test")
		assert any(e["type"] == "intent_updated" and "switch" in e["summary"] for e in events)

	def test_reviewer_gets_no_tools_and_does_not_execute(self, tmp_path):
		provider = ScriptedProvider([{**_tool_call("read_file", {"path": "calc.py"}), "content": "review"}])
		session, tools, _ = _session(tmp_path, [{"role": "assistant", "content": "forge"}], [])
		session.providers["loom"] = provider
		result = session.run("loom", system_prompt="You are Loom.", task="review", tools=None, executor=tools, role="reviewer")
		assert result["tool_calls"] == 0
		assert result["text"] == "review"
		turns = session.mirror.read_turns("alma-mini-test")
		assert all(t["role"] != "tool" for t in turns)

	def test_switch_across_instances_closes_previous_leg(self, tmp_path):
		from red_pill.mini.profiles import PROFILES

		session_a, tools_a, _ = _session(tmp_path, [{"role": "assistant", "content": "forge"}])
		session_a.profiles = PROFILES
		session_a.toolboxes = {"workspace": tools_a}
		session_a.run_profile("forge", "fix")
		session_b = MiniSession(
			MiniConfig(
				workspace=str(tmp_path / "ws"),
				continuity_id="alma-mini-test",
				mission_id="mission:mini-test",
				db_path=str(tmp_path / "session.db"),
				affinity=["mission:mini-test"],
			),
			{"forge": ScriptedProvider([]), "loom": ScriptedProvider([{"role": "assistant", "content": "review"}])},
			profiles=PROFILES,
			toolboxes={"workspace": tools_a},
		)
		session_b.run_profile("loom", "review")
		rows = session_b.registry.get_by_continuity("alma-mini-test")
		active = [r for r in rows if r.get("ttl_state") != "expired"]
		assert len(active) == 1
		assert active[0]["originator"].startswith("loom:")

	def test_switching_back_closes_loom(self, tmp_path):
		session, _, _ = _session(
			tmp_path,
			[{"role": "assistant", "content": "forge1"}],
			[{"role": "assistant", "content": "loom"}],
		)
		session.providers["forge"].script.append({"role": "assistant", "content": "forge2"})
		session.run("forge", system_prompt="You are Forge.", task="a", tools=None)
		session.run("loom", system_prompt="You are Loom.", task="b", tools=None, role="reviewer")
		session.run("forge", system_prompt="You are Forge.", task="c", tools=None)
		rows = session.registry.get_by_continuity("alma-mini-test")
		active = [r for r in rows if r.get("ttl_state") != "expired"]
		assert len(active) == 1
		assert active[0]["originator"].startswith("forge:")
		assert any(r["ttl_state"] == "expired" and r["originator"].startswith("loom:") for r in rows)


def test_fixture_has_nonce_and_bug(tmp_path):
	fixture = prepare_fixture(str(tmp_path / "smoke"))
	assert fixture["run_id"] in (tmp_path / "smoke" / "test_calc.py").read_text()
	assert "return values[n // 2]" in (tmp_path / "smoke" / "calc.py").read_text()
	assert PHASE1_TASK.startswith("Task:")


class TestProfiles:
	def test_forge_profile_renders_identity_without_bunker(self):
		from red_pill.mini.profiles import PROFILES

		text = PROFILES["forge"].render_system(session_short="abc12345", operator="Joan")
		assert "Forge" in text and "Joan" in text and "abc12345" in text
		assert "BUNKER" not in text and "handshake" not in text.lower()

	def test_run_profile_uses_profile_prompt_provider_and_toolbox(self, tmp_path):
		from red_pill.mini.profiles import PROFILES

		provider = ScriptedProvider([{"role": "assistant", "content": "done"}])
		session, tools, _ = _session(tmp_path, [])
		session.providers["forge"] = provider
		session.profiles = PROFILES
		session.toolboxes = {"workspace": tools}
		result = session.run_profile("forge", "read calc.py")
		system = provider.calls[0]["messages"][0]["content"]
		assert "Forge" in system and "Joan" in system
		assert provider.calls[0]["tools"] == tools.schemas
		assert result["body"] == "forge"
		assert result["tool_calls"] == 0

	def test_run_profile_loom_has_no_tools(self, tmp_path):
		from red_pill.mini.profiles import PROFILES

		provider = ScriptedProvider([{"role": "assistant", "content": "review"}])
		session, tools, _ = _session(tmp_path, [{"role": "assistant", "content": "forge"}])
		session.providers["loom"] = provider
		session.profiles = PROFILES
		session.toolboxes = {"workspace": tools}
		session.run_profile("forge", "fix")
		result = session.run_profile("loom", "review")
		assert result["tool_calls"] == 0
		assert "Loom" in provider.calls[0]["messages"][0]["content"]
		assert provider.calls[0]["tools"] is None
		active = [r for r in session.registry.get_by_continuity("alma-mini-test") if r.get("ttl_state") != "expired"]
		assert len(active) == 1
		assert active[0]["originator"].startswith("loom:")

	def test_workspace_tools_exposes_schemas(self, tmp_path):
		tools = WorkspaceTools(str(tmp_path))
		assert tools.schemas == TOOL_SCHEMAS


class TestReadOnlyLoom:
	def test_read_only_toolbox_hides_write_tools(self, tmp_path):
		tools = WorkspaceTools(str(tmp_path), read_only=True)
		names = {schema["function"]["name"] for schema in tools.schemas}
		assert names == {"list_files", "read_file", "run_tests"}
		with pytest.raises(ToolError):
			tools.write_file("x.py", "x")
		with pytest.raises(ToolError):
			tools.edit_file("x.py", "a", "b")

	def test_loom_tools_profile_uses_read_only_toolbox(self):
		from red_pill.mini.profiles import PROFILES

		profile = PROFILES["loom-tools"]
		assert profile.toolbox == "workspace_ro"
		assert "READ-ONLY" in profile.render_system(session_short="abc", operator="Joan")
