"""Hook post-turno externo y safety net active-only (B-02)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.session.compaction_hook import maybe_start_after_turn, sweep_active_compactions
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry


def _config(monkeypatch):
	monkeypatch.setattr(
		"red_pill.config.get_config",
		lambda: SimpleNamespace(
			SESSION_COMPACTOR_ENABLED=True,
			SESSION_COMPACTOR_ENGINE="extractive",
			SESSION_COMPACTOR_BACKGROUND_TOKENS=1,
			SESSION_COMPACTOR_RESERVE_TOKENS=1,
			SESSION_COMPACTOR_PROTECT_LAST_N=4,
			SESSION_COMPACTOR_MAX_INPUT_CHARS=120000,
			SESSION_COMPACTOR_JOB_PRIORITY=4,
			COMPACTOR_SCOPE="autonomous",
			COMPACTOR_SCOPE_PREFIXES="job:,telegram:,local:,mini:,forge:,loom:,d23-review:,awakening:",
			COMPACTOR_SWEEP_ACTIVE_MIN=15,
		),
	)


@pytest.fixture
def db_path(tmp_path):
	return str(tmp_path / "session.db")


def _seed_mirror(mirror, continuity: str, originator: str):
	mirror.append_turn(
		continuity_id=continuity,
		mission_id="repo:next",
		role="user",
		content="hola",
		originator=originator,
		source="external_hook",
		source_ref=f"{continuity}:1",
		status="completed",
	)


def test_sweep_active_only_and_scope(monkeypatch, db_path):
	_config(monkeypatch)
	registry = SessionRegistry(db_path)
	for originator, continuity in (
		("job:test", "alma-job"),
		("opencode:ses_user", "alma-user"),
		("job:inactive", "alma-inactive"),
	):
		registry.upsert_session(
			originator=originator,
			continuity_id=continuity,
			mission_id="repo:next",
			role="task",
		)
	registry.unregister_session("job:inactive")
	qm = CognitiveQueueManager(db_path + ".queue")
	result = sweep_active_compactions(db_path=db_path, queue_manager=qm)
	assert result["enabled"] is True
	assert result["scanned"] == 2  # job + opencode; expired fuera
	assert result["enqueued"] == 1  # opencode interactivo fuera por scope
	found = qm.find_task_by_payload_key(source="script_job", key="continuity_id", value="alma-job")
	assert found is not None
	assert len(qm.list_tasks()) == 1


def test_maybe_start_after_turn_scope(monkeypatch, db_path):
	_config(monkeypatch)
	mirror = SessionMirror(db_path)
	qm = CognitiveQueueManager(db_path + ".queue")
	_seed_mirror(mirror, "alma-job", "job:test")
	job = maybe_start_after_turn(
		mirror,
		"alma-job",
		mission_id="repo:next",
		originator="job:test",
		queue_manager=qm,
	)
	assert job
	_seed_mirror(mirror, "alma-user", "opencode:ses_user")
	assert (
		maybe_start_after_turn(
			mirror,
			"alma-user",
			mission_id="repo:next",
			originator="opencode:ses_user",
			queue_manager=qm,
		)
		is None
	)
	assert len(qm.list_tasks()) == 1
