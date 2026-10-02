import asyncio
import os
import time
from unittest.mock import MagicMock

import pytest

from red_pill.core import session_liveness as sl


@pytest.fixture
def live_dir(tmp_path, monkeypatch):
	monkeypatch.setattr(sl, "get_state_dir", lambda: tmp_path)
	return tmp_path / "sessions" / "live"


def test_touch_and_parse(live_dir):
	sl.touch_session("opencode", "ses_abc", "start")
	sl.touch_session("opencode", "ses_abc", "end")
	files = sorted(p.name for p in live_dir.iterdir())
	assert files == ["opencode__ses_abc.end", "opencode__ses_abc.start"]
	assert sl.parse_filename("opencode__ses_abc.start") == ("opencode", "ses_abc", "start")
	assert sl.parse_filename("garbage.txt") is None
	assert sl.parse_filename("no_delim.log") is None


def test_touch_guards(live_dir):
	assert sl.touch_session("", "s", "start") is None
	assert sl.touch_session("p", "", "start") is None
	assert sl.touch_session("p", "s", "bogus") is None


def test_list_sessions_pair_and_in_flight(live_dir):
	# uuid-1: par completo y ANTIGUO → no en vuelo
	s_start = sl.touch_session("claude_code", "uuid-1", "start")
	s_end = sl.touch_session("claude_code", "uuid-1", "end")
	old = time.time() - 500
	os.utime(s_start, (old, old))
	os.utime(s_end, (old + 10, old + 10))
	# ses_2: start nuevo sin end → en vuelo
	sl.touch_session("opencode", "ses_2", "start")

	sessions = {s.session_id: s for s in sl.list_sessions()}
	assert set(sessions) == {"uuid-1", "ses_2"}
	assert not sessions["uuid-1"].in_flight
	assert sessions["ses_2"].in_flight
	assert sl.list_sessions()[0].session_id == "ses_2"  # más reciente primero
	assert sessions["ses_2"].is_active(active_seconds=600)
	assert not sessions["uuid-1"].is_active(active_seconds=600)


def test_janitor_purges_old_keeps_fresh(live_dir):
	from red_pill.swarm.agents.janitor import JanitorMinion
	from red_pill.swarm.agents.janitor_plugins.session_liveness import SessionLivenessPlugin

	old = sl.touch_session("opencode", "old", "start")
	fresh = sl.touch_session("opencode", "fresh", "end")
	old_time = time.time() - 100 * 3600
	os.utime(old, (old_time, old_time))

	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())
	res = asyncio.run(SessionLivenessPlugin().execute(janitor, {"plugins": {"session_liveness": {"ttl_h": 48}}}))

	assert res["session_liveness_purged"] == 1
	assert not old.exists()
	assert fresh.exists()


def test_readers_do_not_create_the_live_dir(live_dir):
	"""Lector y limpiador no crean `sessions/live` (AD-043): sin latidos → vacío."""
	from red_pill.swarm.agents.janitor import JanitorMinion
	from red_pill.swarm.agents.janitor_plugins.session_liveness import SessionLivenessPlugin

	assert sl.list_sessions() == []
	janitor = JanitorMinion()
	object.__setattr__(janitor, "log", MagicMock())
	res = asyncio.run(SessionLivenessPlugin().execute(janitor, {"plugins": {}}))
	assert res["session_liveness_purged"] == 0
	assert not live_dir.exists()
	# el escritor sí lo crea
	assert sl.touch_session("opencode", "s", "start") is not None
	assert live_dir.is_dir()
