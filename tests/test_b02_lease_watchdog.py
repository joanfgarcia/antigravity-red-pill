"""B-02 — heartbeat de compactación y watchdog de leases."""

from __future__ import annotations

import asyncio
import time
from argparse import Namespace
from types import SimpleNamespace

from red_pill.session.lease import LeaseStore
from red_pill.swarm.agents.janitor_plugins.lease_sweep import LeaseSweepPlugin


def test_lease_sweep_plugin_counts(monkeypatch):
	class FakeLease:
		def sweep(self, *, mark_stalled: bool = True):
			return [{"lease_key": "compact:alma"}]

	monkeypatch.setattr(
		"red_pill.swarm.agents.janitor_plugins.lease_sweep.LeaseStore",
		lambda: FakeLease(),
	)
	janitor = SimpleNamespace(log=lambda *args, **kwargs: None)
	out = asyncio.run(LeaseSweepPlugin().execute(janitor, {}))
	assert out["lease_sweep_stalled"] == 1


def test_lease_sweep_marks_stalled(tmp_path):
	store = LeaseStore(str(tmp_path / "session.db"))
	store.begin_work_lease("compact:alma", continuity_id="alma", idle_ttl_s=60, max_wall_s=120)
	expired = store.sweep(now=time.time() + 1000)
	assert expired and expired[0]["lease_key"] == "compact:alma"
	assert store.get("compact:alma")["state"] == "stalled"


def test_cli_compact_takes_and_finishes_lease(tmp_path, monkeypatch):
	from red_pill.cli_services import handle_session

	calls: list[tuple] = []

	class FakeLease:
		def __init__(self, db_path=None):
			pass

		def begin_work_lease(self, key, **kwargs):
			calls.append(("begin", key, kwargs.get("continuity_id")))
			return {}

		def heartbeat(self, key, **kwargs):
			calls.append(("beat", key))
			return {}

		def finish(self, key, **kwargs):
			calls.append(("finish", key, kwargs.get("state")))
			return {}

	class FakeCompactor:
		def __init__(self, mirror, **kwargs):
			pass

		def compact_now(self, continuity, **kwargs):
			return {
				"compaction_id": "c1",
				"range_start_seq": 1,
				"range_end_seq": 2,
				"status": "completed",
			}

	monkeypatch.setattr("red_pill.session.lease.LeaseStore", FakeLease)
	monkeypatch.setattr("red_pill.session.compactor.Compactor", FakeCompactor)
	args = Namespace(
		session_cmd="compact",
		continuity="alma",
		mission="repo:next",
		engine=None,
		protect_last_n=None,
		handoff=None,
		json=False,
		db_path=str(tmp_path / "session.db"),
	)
	handle_session(args)
	assert calls[0] == ("begin", "compact:alma", "alma")
	assert calls[-1] == ("finish", "compact:alma", "completed")
