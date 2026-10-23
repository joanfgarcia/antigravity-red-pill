"""Rol transparente (env/registro, nunca el modelo) + hidratación por rol."""

from unittest.mock import patch

from red_pill.mcp_server import _coro_digest, _resolve_session_identity
from red_pill.session.roles import policy_for
from red_pill.session.store import SessionRegistry


def test_policy_registry():
	assert policy_for("orchestrator").references()["digest"] == "global"
	assert policy_for("task").references()["digest"] == "compact"
	assert policy_for("spawn").references()["digest"] == "none"
	assert policy_for("desconocido").references()["digest"] == "compact"


async def test_role_is_inherited_from_registry_not_from_model(tmp_path, monkeypatch):
	bridge = {"originator": "opencode:role1", "workdir": str(tmp_path)}
	monkeypatch.setenv("REDPILL_ROLE", "orchestrator")
	with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
		with patch("red_pill.mcp_server._current_git_branch", return_value="feat/r"):
			first = await _resolve_session_identity({"user_prompt": "x"})
	assert first["role"] == "orchestrator"
	monkeypatch.delenv("REDPILL_ROLE")
	with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
		with patch("red_pill.mcp_server._current_git_branch", return_value="feat/r"):
			second = await _resolve_session_identity({"user_prompt": "x", "role": "spawn"})
	assert second["role"] == "orchestrator"


async def test_campaign_inherits_and_model_args_do_not_redirect(tmp_path, monkeypatch):
	bridge = {"originator": "opencode:role2", "workdir": str(tmp_path)}
	monkeypatch.setenv("REDPILL_CAMPAIGN_ID", "camp:1")
	with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
		with patch("red_pill.mcp_server._current_git_branch", return_value="feat/r"):
			await _resolve_session_identity({"user_prompt": "x"})
	monkeypatch.delenv("REDPILL_CAMPAIGN_ID")
	with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
		with patch("red_pill.mcp_server._current_git_branch", return_value="feat/r"):
			ident = await _resolve_session_identity(
				{"user_prompt": "x", "campaign_id": "camp:other", "mission_id": "repo:evil"}
			)
	row = SessionRegistry().get_by_originator("opencode:role2")
	assert row["campaign_id"] == "camp:1"
	assert row["mission_id"] == "repo:feat/r"
	assert ident["mission_id"] == "repo:feat/r"


def test_spawn_gets_no_digest_even_with_events():
	reg = SessionRegistry()
	reg.add_event(event_type="phase_done", mission_id="repo:m", summary="x")
	identity = {
		"originator": "opencode:spawn1",
		"continuity_id": "alma-s",
		"mission_id": "repo:m",
		"role": "spawn",
		"previous_event_seq": 0,
	}
	assert _coro_digest(identity, reg.get_max_event_seq()) is None


def test_orchestrator_sees_global_missions():
	reg = SessionRegistry()
	reg.upsert_session(originator="opencode:o1", continuity_id="alma-o", mission_id="repo:a", role="orchestrator")
	reg.upsert_session(originator="opencode:t1", continuity_id="alma-t", mission_id="repo:b")
	identity = {
		"originator": "opencode:o1",
		"continuity_id": "alma-o",
		"mission_id": "repo:a",
		"role": "orchestrator",
		"previous_event_seq": 0,
	}
	digest = _coro_digest(identity, reg.get_max_event_seq())
	assert digest and "misiones vivas" in digest
