"""Alcance del compactor en background (autonomous/all/off)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from red_pill.session.mirror import SessionMirror
from red_pill.session.scope import compactor_scope_allows


@pytest.fixture
def mirror(tmp_path):
	return SessionMirror(str(tmp_path / "session.db"))


def _seed(mirror, n: int = 8, continuity: str = "alma-1") -> None:
	for i in range(1, n + 1):
		mirror.append_turn(
			continuity_id=continuity,
			mission_id="repo:next",
			role="user" if i % 2 else "assistant",
			content=f"turno {i}",
			source_ref=f"t{i}",
			ts=float(i),
		)


def _config(monkeypatch, scope: str, prefixes: str = "job:,telegram:,local:,mini:,forge:,loom:,d23-review:,awakening:"):
	monkeypatch.setattr(
		"red_pill.config.get_config",
		lambda: SimpleNamespace(COMPACTOR_SCOPE=scope, COMPACTOR_SCOPE_PREFIXES=prefixes),
	)


def test_autonomous_includes_mission_telegram_local_and_not_interactive(monkeypatch):
	_config(monkeypatch, "autonomous")
	assert compactor_scope_allows("job:abc")
	assert compactor_scope_allows("telegram:abc")
	assert compactor_scope_allows("local:mini")
	assert compactor_scope_allows("forge:run")
	assert compactor_scope_allows("d23-review:decision")
	assert compactor_scope_allows("opencode:ses_wake", origin="awakening")
	assert compactor_scope_allows("opencode:ses_job", origin="job")
	assert compactor_scope_allows("pi:ses_job", origin="job")
	assert compactor_scope_allows("claude_code:ses_wake", origin="awakening")
	assert not compactor_scope_allows("opencode:ses_user", origin="user")
	assert not compactor_scope_allows("pi:ses_user", origin="user")
	assert not compactor_scope_allows("claude_code:ses_user", origin="user")
	assert not compactor_scope_allows("claude:ses_user", origin="user")
	assert not compactor_scope_allows("antigravity:ses_user", origin="user")
	assert not compactor_scope_allows("")
	assert not compactor_scope_allows("algo-raro")


def test_all_and_off(monkeypatch):
	_config(monkeypatch, "all")
	assert compactor_scope_allows("opencode:ses_user", origin="user")
	assert compactor_scope_allows("pi:ses_user", origin="user")
	assert compactor_scope_allows("algo-raro")
	_config(monkeypatch, "off")
	assert not compactor_scope_allows("job:abc")


def test_maybe_start_respects_scope(mirror, monkeypatch):
	from red_pill.cognitive.queue_manager import CognitiveQueueManager
	from red_pill.session.compactor import Compactor

	_config(monkeypatch, "autonomous")
	qm = CognitiveQueueManager(str(mirror.db_path + ".queue"))
	_seed(mirror, 8)
	compactor = Compactor(mirror, background_tokens=1, queue_manager=qm)
	assert compactor.maybe_start("alma-1", mission_id="repo:next", originator="opencode:ses_user") is None
	assert compactor.maybe_start("alma-1", mission_id="repo:next", originator="pi:ses_user") is None
	job = compactor.maybe_start("alma-1", mission_id="repo:next", originator="job:test")
	assert job
