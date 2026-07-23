"""Lane isolation for the Centralized Job Manager (F1-P0).

The central queue (bunker_queue.db) is shared by several consumers:
- the cognitive lane (DriveEvaluator tasks, consumed by awakenings/IDE worker),
- the samantha lane, and
- the mechanical job lane (ResumableJobDriver jobs, consumed by the runner).

These tests pin the two invariants that keep the lanes watertight:
pops are source-scoped, and curiosity ratings only learn from the
cognitive lane (mechanical job completions must never feed them).
"""

import json

import pytest

from red_pill.cognitive.queue_manager import CognitiveQueueManager


@pytest.fixture
def queue(tmp_path):
	return CognitiveQueueManager(db_path=str(tmp_path / "bunker_queue.db"))


@pytest.fixture
def curiosity_env(tmp_path, monkeypatch):
	"""Isolated XDG env + fresh config so CURIOSITY_ENGINE_ENABLED resolves to its default (True)."""
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
	monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
	monkeypatch.setenv("CURIOSITY_PROFILE", "balanced")

	from red_pill.config import get_config

	get_config.cache_clear()
	yield
	get_config.cache_clear()


def test_scoped_pop_ignores_other_lanes(queue):
	"""A consumer restricted to its lane never steals another lane's tasks."""
	queue.enqueue_task(source="flow_job", payload={"flow_id": "nightly"}, priority=10)
	cognitive_id = queue.enqueue_task(source="drive_evaluator", payload={"action": "autonomous_research", "category": "active_learning"}, priority=1)

	task = queue.pop_next_task(allowed_sources=["drive_evaluator"])

	assert task is not None
	assert task["id"] == cognitive_id
	assert task["source"] == "drive_evaluator"


def test_scoped_pop_returns_none_when_lane_empty(queue):
	"""Only foreign-lane tasks in the queue -> a scoped pop comes back empty."""
	queue.enqueue_task(source="flow_job", payload={"flow_id": "nightly"}, priority=10)

	assert queue.pop_next_task(allowed_sources=["drive_evaluator"]) is None
	# And the mechanical task is still PENDING, untouched.
	assert queue.has_pending(source="flow_job")


def test_curiosity_rating_ignores_mechanical_jobs(queue, curiosity_env, tmp_path, monkeypatch):
	"""mark_completed of a mechanical job must not touch curiosity_ratings.json.

	Without the source guard, an unknown category falls back to dynamic_spark
	with a +0.5 reward, inflating the DriveEvaluator's spark rating.
	"""
	from red_pill.core import paths

	state_dir = tmp_path / "state"
	state_dir.mkdir()
	monkeypatch.setattr(paths, "get_state_dir", lambda: state_dir)

	ratings_file = state_dir / "curiosity_ratings.json"
	baseline = {"balanced": {"dynamic_spark": {"rating": 40.0, "uncertainty": 8.33, "last_rho": 0.5, "executed_count": 0}}}
	ratings_file.write_text(json.dumps(baseline))

	job_id = queue.enqueue_task(source="flow_job", payload={"flow_id": "nightly", "category": "minion_flow"})
	queue.mark_completed(job_id)

	assert json.loads(ratings_file.read_text()) == baseline


def test_curiosity_rating_still_learns_from_cognitive_lane(queue, curiosity_env, tmp_path, monkeypatch):
	"""The guard must not silence the cognitive lane itself."""
	from red_pill.core import paths

	state_dir = tmp_path / "state"
	state_dir.mkdir()
	monkeypatch.setattr(paths, "get_state_dir", lambda: state_dir)

	ratings_file = state_dir / "curiosity_ratings.json"
	baseline = {"balanced": {"dynamic_spark": {"rating": 40.0, "uncertainty": 8.33, "last_rho": 0.5, "executed_count": 0}}}
	ratings_file.write_text(json.dumps(baseline))

	task_id = queue.enqueue_task(source="drive_evaluator", payload={"action": "autonomous_research", "category": "dynamic_spark"})
	queue.mark_completed(task_id)

	updated = json.loads(ratings_file.read_text())
	assert updated["balanced"]["dynamic_spark"]["executed_count"] == 1
	assert updated["balanced"]["dynamic_spark"]["rating"] > 40.0
