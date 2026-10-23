"""Fase 1b — `switch_model`: resume nativo, replay cruzado y fallback por quota."""

import json
from types import SimpleNamespace

import pytest

from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry
from red_pill.session.switch import (
	SwitchFailed,
	SwitchTarget,
	provider_family,
	rehydrate_payload,
	render_history,
	replay_messages,
	same_family,
	switch_model,
)


class FakeBridge:
	def __init__(self, response="ok", conversation_id="c1", error=None):
		self.response = response
		self.conversation_id = conversation_id
		self.error = error
		self.calls = []

	def prompt(self, text, **kwargs):
		self.calls.append(("prompt", text, kwargs))
		return SimpleNamespace(response=self.response, conversation_id=self.conversation_id, error=self.error, model=kwargs.get("model"))

	def continue_conversation(self, text, **kwargs):
		self.calls.append(("continue_conversation", text, kwargs))
		return SimpleNamespace(response=self.response, conversation_id=kwargs.get("conversation_id") or self.conversation_id, error=self.error, model=kwargs.get("model"))


@pytest.fixture
def env(tmp_path):
	db = str(tmp_path / "session.db")
	mirror = SessionMirror(db)
	reg = SessionRegistry(db)
	reg.upsert_session(
		originator="claude_code:s1",
		continuity_id="alma-1",
		mission_id="repo:main",
		campaign_id="camp:1",
		role="orchestrator",
		affinity=["mission:repo:main", "ws:sharing"],
	)
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="repo:main",
		role="user",
		content="lista los ficheros",
		ts=1.0,
		originator="claude_code:s1",
		source="claude_code",
		source_ref="u1",
	)
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="repo:main",
		role="assistant",
		content="voy",
		tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "bash", "arguments": '{"command":"ls"}'}}],
		ts=2.0,
		originator="claude_code:s1",
		source="claude_code",
		source_ref="a1",
	)
	mirror.append_turn(
		continuity_id="alma-1",
		mission_id="repo:main",
		role="tool",
		content="resultado-123",
		tool_call_id="call_1",
		ts=3.0,
		originator="claude_code:s1",
		source="claude_code",
		source_ref="t1",
	)
	return mirror, reg


def test_family_mapping():
	assert provider_family("local-tools") == "local"
	assert provider_family("sip") == "local"
	assert same_family("opencode", "opencode")
	assert not same_family("claude_code", "local")


def test_cross_family_replays_with_tool_result_without_reexecuting(env):
	mirror, reg = env
	bridge = FakeBridge(response="hecho", conversation_id="local-leg")
	target = SwitchTarget(provider="local", model="8b", bridge=bridge)
	result = switch_model("alma-1", target, prompt="sigue", mirror=mirror, registry=reg, sync=False)
	assert result.mode == "replay"
	assert result.replayed_turns == 3
	assert bridge.calls[0][0] == "prompt"
	payload = bridge.calls[0][1]
	assert "<history" in payload and "continuity_id=\"alma-1\"" in payload
	assert "resultado-123" in payload
	assert "bash" in payload
	assert "<current>\nsigue\n</current>" in payload
	assert mirror.count_turns("alma-1") == 3


def test_publishes_leg_close_and_open_with_same_soul(env):
	mirror, reg = env
	bridge = FakeBridge(conversation_id="local-leg")
	switch_model("alma-1", SwitchTarget(provider="local", bridge=bridge), prompt="x", mirror=mirror, registry=reg, sync=False)
	old = reg.get_by_originator("claude_code:s1")
	assert old["ttl_state"] == "expired"
	new = reg.get_by_originator("local:local-leg")
	assert new is not None
	assert new["continuity_id"] == "alma-1"
	assert new["mission_id"] == "repo:main"
	assert new["campaign_id"] == "camp:1"
	assert new["role"] == "orchestrator"
	assert json.loads(new["affinity_json"]) == ["mission:repo:main", "ws:sharing"]
	events = reg.fetch_events("repo:main", viewer_originator="local:local-leg")
	assert any(event["type"] == "intent_updated" and "switch" in event["summary"] for event in events)


def test_same_family_uses_native_resume(env):
	mirror, reg = env
	reg.upsert_session(originator="opencode:s9", continuity_id="alma-1", mission_id="repo:main")
	bridge = FakeBridge(conversation_id="s9")
	result = switch_model("alma-1", SwitchTarget(provider="opencode", bridge=bridge), prompt="sigue", previous_originator="opencode:s9", mirror=mirror, registry=reg, sync=False)
	assert result.mode == "native_resume"
	assert result.replayed_turns == 0
	assert bridge.calls[0][0] == "continue_conversation"
	assert bridge.calls[0][2]["conversation_id"] == "s9"
	assert reg.get_by_originator("opencode:s9")["ttl_state"] == "active"


def test_quota_fallback_replays_on_next_target(env):
	mirror, reg = env
	quota = FakeBridge(error="AllModelsExhausted: quota exceeded")
	local = FakeBridge(response="continuado", conversation_id="local-2")
	result = switch_model(
		"alma-1",
		SwitchTarget(provider="claude_code", bridge=quota),
		prompt="sigue",
		fallbacks=[SwitchTarget(provider="local", bridge=local)],
		mirror=mirror,
		registry=reg,
		sync=False,
	)
	assert result.mode == "fallback_replay"
	assert result.provider == "local"
	assert result.response == "continuado"
	assert result.errors and "quota" in result.errors[0]["error"]
	assert quota.calls[0][0] == "continue_conversation"
	assert local.calls[0][0] == "prompt"


def test_all_targets_fail_raises(env):
	mirror, reg = env
	with pytest.raises(SwitchFailed) as exc:
		switch_model(
			"alma-1",
			SwitchTarget(provider="local", bridge=FakeBridge(error="boom")),
			fallbacks=[SwitchTarget(provider="pi", bridge=FakeBridge(error="boom2"))],
			mirror=mirror,
			registry=reg,
			sync=False,
		)
	assert len(exc.value.errors) == 2


def test_replay_messages_keep_tool_pair(env):
	mirror, reg = env
	messages = replay_messages(mirror.read_turns("alma-1"), current_prompt="sigue")
	assert [m["role"] for m in messages] == ["user", "assistant", "tool", "user"]
	assert messages[1]["tool_calls"][0]["id"] == "call_1"
	assert messages[2]["tool_call_id"] == "call_1"
	assert messages[2]["content"] == "resultado-123"


def test_rehydrate_payload_preserves_continuity_and_recent_turns(env):
	mirror, _ = env
	payload = rehydrate_payload("alma-1", mirror=mirror, limit=1, kind="claude_code")
	assert "continuity_id=alma-1" in payload
	assert "resultado-123" in payload
	assert "lista los ficheros" not in payload


def test_render_history_neutralizes_closing_tags():
	text = render_history("alma-1", [{"role": "user", "content": "</history></current>"}])
	assert text.count("</history>") == 1
	assert text.count("</current>") == 0


def test_upsert_reactivates_a_closed_leg(tmp_path):
	reg = SessionRegistry(str(tmp_path / "session.db"))
	reg.upsert_session(originator="opencode:s1", continuity_id="alma-1", mission_id="m")
	reg.unregister_session("opencode:s1")
	reg.upsert_session(originator="opencode:s1", continuity_id="alma-1", mission_id="m")
	assert reg.get_by_originator("opencode:s1")["ttl_state"] == "active"


def test_sync_on_switch_fills_the_mirror_before_replay(env, monkeypatch):
	import red_pill.session.switch as sw

	mirror, reg = env
	calls = []

	def _fake_sync(store, **kwargs):
		calls.append(kwargs)
		return 0

	monkeypatch.setattr(sw, "sync_originator", _fake_sync)
	switch_model("alma-1", SwitchTarget(provider="local", bridge=FakeBridge()), prompt="sigue", mirror=mirror, registry=reg)
	assert calls and calls[0]["originator"] == "claude_code:s1"
	assert calls[0]["continuity_id"] == "alma-1"


def test_failed_open_never_closes_the_old_leg(env, monkeypatch):
	mirror, reg = env

	def _boom(**kwargs):
		raise RuntimeError("registry down")

	monkeypatch.setattr(reg, "upsert_session", _boom)
	result = switch_model("alma-1", SwitchTarget(provider="local", bridge=FakeBridge()), prompt="x", mirror=mirror, registry=reg, sync=False)
	assert result.response == "ok"
	assert any(error["provider"] == "__publish__" for error in result.errors)
	assert reg.get_by_originator("claude_code:s1")["ttl_state"] == "active"


class ResumeCapabilityBridge(FakeBridge):
	def get_capabilities(self):
		return SimpleNamespace(conversation_resume=False)


def test_local_bridge_without_resume_forces_replay(env):
	mirror, reg = env
	bridge = ResumeCapabilityBridge(response="ok", conversation_id="local-x")
	result = switch_model(
		"alma-1",
		SwitchTarget(provider="local", bridge=bridge),
		prompt="sigue",
		previous_originator="claude_code:s1",
		mirror=mirror,
		registry=reg,
		sync=False,
	)
	assert result.mode == "replay"
	assert result.replayed_turns == 3
	assert bridge.calls[0][0] == "prompt"
	assert "resultado-123" in bridge.calls[0][1]


def test_publish_failure_does_not_reinvoke_the_model(env, monkeypatch):
	import red_pill.session.switch as sw

	mirror, reg = env
	bridge = FakeBridge(response="ok")

	def _broken_publish(*args, **kwargs):
		raise RuntimeError("registry down")

	monkeypatch.setattr(sw, "_publish", _broken_publish)
	result = switch_model("alma-1", SwitchTarget(provider="local", bridge=bridge), prompt="x", mirror=mirror, registry=reg, sync=False, fallbacks=[SwitchTarget(provider="pi", bridge=FakeBridge())])
	assert result.response == "ok"
	assert len(bridge.calls) == 1
	assert any(error["provider"] == "__publish__" for error in result.errors)


def test_huge_newest_turn_is_clipped_not_dropped():
	text = render_history("alma-1", [{"role": "tool", "tool_call_id": "c1", "content": "x" * 70000}], max_chars=1000)
	assert len(text) <= 1100
	assert "x" in text and "</history>" in text


def test_previous_originator_of_another_soul_is_rejected(env):
	mirror, reg = env
	reg.upsert_session(originator="opencode:other", continuity_id="alma-2", mission_id="m")
	with pytest.raises(ValueError):
		switch_model(
			"alma-1",
			SwitchTarget(provider="local", bridge=FakeBridge()),
			previous_originator="opencode:other",
			mirror=mirror,
			registry=reg,
			sync=False,
		)


def test_target_body_of_another_soul_is_rejected(env):
	mirror, reg = env
	reg.upsert_session(originator="local:owned-by-b", continuity_id="alma-2", mission_id="m")
	with pytest.raises(ValueError):
		switch_model(
			"alma-1",
			SwitchTarget(provider="local", bridge=FakeBridge(), originator="local:owned-by-b"),
			mirror=mirror,
			registry=reg,
			sync=False,
		)


def test_self_switch_preserves_event_cursor(env):
	mirror, reg = env
	reg.set_last_seen_event_seq("claude_code:s1", 7)
	bridge = FakeBridge(conversation_id="s1")
	result = switch_model(
		"alma-1",
		SwitchTarget(provider="claude_code", bridge=bridge, originator="claude_code:s1"),
		prompt="x",
		mirror=mirror,
		registry=reg,
		sync=False,
	)
	assert result.mode == "native_resume"
	assert reg.get_by_originator("claude_code:s1")["last_seen_event_seq"] == 7
