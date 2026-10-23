"""Fase 2 resto — `fetch_divergent_turns`: reloj + filtro D15 + contenido del espejo."""

import pytest

from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry
from red_pill.session.switch import render_history


@pytest.fixture
def env(tmp_path):
	db = str(tmp_path / "session.db")
	reg = SessionRegistry(db)
	mirror = SessionMirror(db)
	return reg, mirror


def _seed(reg, mirror):
	own_turn = reg.next_global_turn("opencode:me", ["mission:repo:m", "ws:x"])
	ally_turn = reg.next_global_turn("opencode:ally", ["mission:repo:m"])
	foreign_turn = reg.next_global_turn("opencode:foreign", ["mission:repo:other"])
	reg.upsert_session(originator="opencode:me", continuity_id="alma-me", mission_id="repo:m", affinity=["mission:repo:m", "ws:x"])
	reg.upsert_session(originator="opencode:ally", continuity_id="alma-ally", mission_id="repo:m", affinity=["mission:repo:m"])
	reg.upsert_session(originator="opencode:foreign", continuity_id="alma-foreign", mission_id="repo:other", affinity=["mission:repo:other"])
	mirror.append_turn(
		continuity_id="alma-me", mission_id="repo:m", role="user", content="mío",
		global_turn=own_turn, originator="opencode:me", source="opencode", source_ref="m1",
	)
	mirror.append_turn(
		continuity_id="alma-ally", mission_id="repo:m", role="user", content="aliado",
		global_turn=ally_turn, originator="opencode:ally", source="opencode", source_ref="a1",
	)
	mirror.append_turn(
		continuity_id="alma-foreign", mission_id="repo:other", role="user", content="ajeno",
		global_turn=foreign_turn, originator="opencode:foreign", source="opencode", source_ref="f1",
	)
	return own_turn, ally_turn, foreign_turn


def test_d15_own_and_intersected_only(env):
	reg, mirror = env
	_seed(reg, mirror)
	items = reg.divergent_turns(0, viewer_originator="opencode:me", viewer_affinity=["mission:repo:m", "ws:x"])
	assert [i["originator"] for i in items] == ["opencode:me", "opencode:ally"]
	assert items[0]["turns"][0]["content"] == "mío"
	assert items[1]["turns"][0]["content"] == "aliado"


def test_empty_affinity_does_not_return_all(env):
	reg, mirror = env
	_seed(reg, mirror)
	items = reg.divergent_turns(0, viewer_originator="opencode:me", viewer_affinity=[])
	assert [i["originator"] for i in items] == ["opencode:me"]


def test_allow_all_is_explicit(env):
	reg, mirror = env
	_seed(reg, mirror)
	items = reg.divergent_turns(0, viewer_originator="opencode:me", viewer_affinity=[], allow_all=True)
	assert len(items) == 3


def test_backfill_turns_have_no_content(env):
	reg, mirror = env
	_seed(reg, mirror)
	mirror.append_turn(
		continuity_id="alma-me", mission_id="repo:m", role="user", content="histórico",
		global_turn=0, originator="opencode:me", source="opencode", source_ref="old",
	)
	items = reg.divergent_turns(0, viewer_originator="opencode:me", viewer_affinity=[])
	assert len(items) == 1
	assert all(t["content"] != "histórico" for t in items[0]["turns"])


def test_since_cursor_excludes_old_turns(env):
	reg, mirror = env
	own, ally, _ = _seed(reg, mirror)
	items = reg.divergent_turns(own, viewer_originator="opencode:me", viewer_affinity=["mission:repo:m"])
	assert [i["global_turn"] for i in items] == [ally]


class TestMCPDivergence:
	@staticmethod
	async def _call(name, arguments):
		from red_pill.mcp_server import handle_call_tool

		return (await handle_call_tool(name, arguments))[0].text

	@staticmethod
	async def _handshake(arguments):
		from types import SimpleNamespace
		from unittest.mock import patch

		from red_pill.mcp_server import handle_call_tool

		async def _fake_interceptor(args):
			return [SimpleNamespace(text="ok")]

		with patch("red_pill.mcp_server.handle_interceptor_rp", new=_fake_interceptor):
			return await handle_call_tool("sovereign_handshake", arguments)

	async def test_without_body_denies(self, tmp_path):
		import os
		from unittest.mock import patch

		with patch("red_pill.mcp_server._harness_bridge", return_value={"originator": "", "workdir": ""}):
			with patch.dict(os.environ, {"REDPILL_ORIGINATOR": "", "REDPILL_HARNESS": ""}):
				out = await self._call("fetch_divergent_turns", {})
		assert "deny-by-default" in out

	async def test_filter_cannot_widen_visibility(self, tmp_path):
		from unittest.mock import patch

		from red_pill.session.store import SessionRegistry

		bridge = {"originator": "opencode:dv1", "workdir": str(tmp_path)}
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="feat/dv"):
				await self._handshake({"user_prompt": "x"})
		SessionRegistry().next_global_turn("opencode:foreign", ["mission:repo:other"])
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="feat/dv"):
				out = await self._call("fetch_divergent_turns", {"since_global_turn": 0})
				assert "opencode:dv1" in out
				assert "opencode:foreign" not in out
				out2 = await self._call(
					"fetch_divergent_turns",
					{"since_global_turn": 0, "affinity_filter": ["mission:repo:other"]},
				)
		# El modelo no puede auto-otorgarse lectura de otra misión con el filtro.
		assert "opencode:foreign" not in out2

	async def test_allow_all_only_with_operator_flag(self, tmp_path):
		from unittest.mock import patch

		from red_pill.session.store import SessionRegistry

		bridge = {"originator": "opencode:dv2", "workdir": str(tmp_path)}
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="feat/dv"):
				await self._handshake({"user_prompt": "x"})
		SessionRegistry().next_global_turn("opencode:foreign2", ["mission:repo:other"])
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="feat/dv"):
				with patch("red_pill.config.get_config") as get_config:
					get_config.return_value = type("C", (), {"MULTISESSION_DIVERGENT_ALLOW_ALL": True})()
					out = await self._call("fetch_divergent_turns", {"since_global_turn": 0})
		assert "opencode:foreign2" in out


def test_visible_turn_not_starved_by_foreign_noise(env):
	reg, _ = env
	for index in range(30):
		reg.next_global_turn(f"opencode:noise{index}", ["mission:other"])
	own = reg.next_global_turn("opencode:me", ["mission:repo:m"])
	items = reg.divergent_turns(0, viewer_originator="opencode:me", viewer_affinity=[], limit=1)
	assert [i["global_turn"] for i in items] == [own]


def test_negative_cursor_is_clamped(env):
	reg, _ = env
	own = reg.next_global_turn("opencode:me", [])
	items = reg.divergent_turns(-50, viewer_originator="opencode:me", viewer_affinity=[], limit=5)
	assert [i["global_turn"] for i in items] == [own]


def test_corrupt_tool_calls_json_does_not_break(env):
	reg, mirror = env
	turn = reg.next_global_turn("opencode:me", [])
	mirror.append_turn(
		continuity_id="alma-me", mission_id="m", role="assistant", content="x",
		global_turn=turn, originator="opencode:me", source="opencode", source_ref="corrupt",
	)
	from red_pill.session.store import connect_session_db

	with connect_session_db(mirror.db_path) as conn:
		conn.execute("UPDATE session_mirror SET tool_calls = '{not json' WHERE source_ref = 'corrupt'")
		conn.commit()
	items = reg.divergent_turns(0, viewer_originator="opencode:me", viewer_affinity=[])
	assert items[0]["turns"][0]["tool_calls"] is None
	with connect_session_db(mirror.db_path) as conn:
		conn.execute("UPDATE session_mirror SET tool_calls = '{\"oops\": 1}' WHERE source_ref = 'corrupt'")
		conn.commit()
	items = reg.divergent_turns(0, viewer_originator="opencode:me", viewer_affinity=[])
	assert items[0]["turns"][0]["tool_calls"] is None
	assert render_history("alma-me", mirror.read_turns("alma-me")).count("<history") == 1

	async def test_model_affinity_in_handshake_cannot_open_foreign_turns(self, tmp_path):
		from unittest.mock import patch

		from red_pill.session.store import SessionRegistry

		bridge = {"originator": "opencode:dv3", "workdir": str(tmp_path)}
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="feat/dv"):
				await self._handshake({"user_prompt": "x", "affinity": ["mission:repo:other"]})
		SessionRegistry().next_global_turn("opencode:foreign3", ["mission:repo:other"])
		row = SessionRegistry().get_by_originator("opencode:dv3")
		assert "mission:repo:other" not in row["affinity_json"]
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="feat/dv"):
				out = await self._call("fetch_divergent_turns", {})
		assert "opencode:foreign3" not in out

	async def test_default_cursor_does_not_hide_previous_foreign_turns(self, tmp_path):
		from unittest.mock import patch

		from red_pill.session.store import SessionRegistry

		SessionRegistry().next_global_turn("opencode:foreign4", ["mission:repo:other"])
		bridge = {"originator": "opencode:dv4", "workdir": str(tmp_path)}
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="feat/dv"):
				await self._handshake({"user_prompt": "x"})
				with patch("red_pill.config.get_config") as get_config:
					get_config.return_value = type("C", (), {"MULTISESSION_DIVERGENT_ALLOW_ALL": True})()
					out = await self._call("fetch_divergent_turns", {})
		assert "opencode:foreign4" in out
