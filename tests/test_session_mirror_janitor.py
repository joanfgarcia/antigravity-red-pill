"""Janitor del espejo: purga conservadora + métricas y señales medibles."""

import time

from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry
from red_pill.swarm.agents.janitor_plugins.session_mirror import SessionMirrorPurgePlugin


class FakeJanitor:
	def __init__(self):
		self.lines = []

	def log(self, message):
		self.lines.append(message)


class FakeMemory:
	def __init__(self):
		self.signals = []

	def inject_signal(self, **kwargs):
		self.signals.append(kwargs)


def _seed_dead_soul():
	mirror = SessionMirror()
	reg = SessionRegistry()
	reg.upsert_session(originator="opencode:dead", continuity_id="alma-dead", mission_id="m")
	reg.unregister_session("opencode:dead")
	mirror.append_turn(
		continuity_id="alma-dead",
		mission_id="m",
		role="user",
		content="viejo",
		ts=time.time() - 90 * 86400,
		originator="opencode:dead",
		source="opencode",
		source_ref="1",
	)
	return mirror


async def test_purges_dead_soul_and_reports_metrics():
	mirror = _seed_dead_soul()
	memory = FakeMemory()
	janitor = FakeJanitor()
	result = await SessionMirrorPurgePlugin().execute(
		janitor, {"plugins": {"session_mirror_purge": {"retention_days": 30}}}, memory_manager=memory
	)
	assert result["session_mirror_rows_purged"] == 1
	assert result["session_mirror_souls_purged"] == 1
	assert result["session_mirror_rows_after"] == 0
	assert mirror.count_turns("alma-dead") == 0
	status = [s for s in memory.signals if s["name"] == "session_mirror_stats"]
	assert status and status[0]["signal_type"] == "status"
	assert not [s for s in memory.signals if s["name"] == "session_mirror_growth"]


async def test_growth_emits_pain_but_does_not_purge_live_soul():
	mirror = SessionMirror()
	reg = SessionRegistry()
	reg.upsert_session(originator="opencode:live", continuity_id="alma-live", mission_id="m")
	mirror.append_turn(
		continuity_id="alma-live",
		mission_id="m",
		role="user",
		content="vivo",
		ts=time.time() - 900 * 86400,
		originator="opencode:live",
		source="opencode",
		source_ref="1",
	)
	memory = FakeMemory()
	result = await SessionMirrorPurgePlugin().execute(
		FakeJanitor(),
		{"plugins": {"session_mirror_purge": {"retention_days": 30, "growth_rows": 0}}},
		memory_manager=memory,
	)
	assert result["session_mirror_rows_purged"] == 0
	assert mirror.count_turns("alma-live") == 1
	assert [s for s in memory.signals if s["name"] == "session_mirror_growth"]


async def test_signal_failure_never_breaks_the_sweep():
	_seed_dead_soul()

	class BrokenMemory:
		def inject_signal(self, **kwargs):
			raise RuntimeError("qdrant down")

	result = await SessionMirrorPurgePlugin().execute(
		FakeJanitor(), {"plugins": {"session_mirror_purge": {"retention_days": 30}}}, memory_manager=BrokenMemory()
	)
	assert result["session_mirror_rows_purged"] == 1


def test_plugin_is_discovered_by_the_janitor():
	from red_pill.swarm.agents.janitor import discover_plugins

	names = {plugin.name for plugin in discover_plugins()}
	assert "session_mirror_purge" in names


async def test_budget_metrics_and_pain_signal():
	from red_pill.swarm.agents.janitor_plugins.session_mirror import _emit_signals

	memory = FakeMemory()
	after = {
		"rows": 10,
		"db_bytes": 99,
		"wal_bytes": 1,
		"budget_bytes": 100,
		"budget_pct": 100.0,
		"over_budget": True,
		"expired_candidates": 0,
	}
	metrics = {"session_mirror_budget_pct": 100.0}
	_emit_signals(memory, metrics, after, growth_rows=10**9, growth_bytes=10**12)
	names = [signal["name"] for signal in memory.signals]
	assert "session_mirror_stats" in names
	assert "session_mirror_budget" in names


async def test_janitor_reports_budget_keys():
	mirror = SessionMirror()
	mirror.append_turn(continuity_id="alma-x", mission_id="m", role="user", content="x", ts=time.time())
	result = await SessionMirrorPurgePlugin().execute(FakeJanitor(), {"plugins": {"session_mirror_purge": {"retention_days": 30}}}, memory_manager=FakeMemory())
	for key in ("session_mirror_budget_bytes", "session_mirror_budget_pct", "session_registry_expired", "session_mirror_stub_rows"):
		assert key in result
