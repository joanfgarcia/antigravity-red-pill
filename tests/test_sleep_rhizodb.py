import json
import time
from unittest.mock import MagicMock

import pytest

from red_pill.metabolism import maintenance as maint
from red_pill.metabolism.sleep import run_rhizodb_washout_and_pruning


def _mock_manager(points=None, scroll_pages=None):
	mock_mem_mgr = MagicMock()
	mock_client = mock_mem_mgr.client
	mock_client.collection_exists.return_value = True
	if scroll_pages is not None:
		mock_client.scroll.side_effect = scroll_pages
	else:
		mock_client.scroll.return_value = (points or [], None)
	return mock_mem_mgr, mock_client


def _updated_ids(mock_client):
	updated = []
	for call in mock_client.batch_update_points.call_args_list:
		for op in call[1]["update_operations"]:
			updated.extend(op.set_payload.points)
	return updated


def test_run_rhizodb_washout_and_pruning():
	# Create mock memory manager and qdrant client
	mock_mem_mgr = MagicMock()
	mock_client = mock_mem_mgr.client

	# Make sure collection_exists returns True
	mock_client.collection_exists.return_value = True

	# Define mock engrams:
	# 1. Immune engram (should be skipped)
	p_immune = MagicMock()
	p_immune.id = "immune_engram"
	p_immune.payload = {"reinforcement_score": 0.8, "stability": 10.0, "immune": True, "last_recalled_at": time.time()}

	# 2. Strong engram (score 0.8, stability 200.0, recalled just now)
	# Washout: gamma=0.85, S_max=365.0
	# b(s_v) = 0.15 * (200.0 / 365.0) = 0.082
	# new_score = 0.85 * 0.8 + 0.082 = 0.68 + 0.082 = 0.762
	# Should be updated, not pruned
	p_strong = MagicMock()
	p_strong.id = "strong_engram"
	p_strong.payload = {"reinforcement_score": 0.8, "stability": 200.0, "immune": False, "last_recalled_at": time.time()}

	# 3. Weak engram that triggers pruning (score 0.09, stability 2.0)
	# Should be pruned (new_score < 0.1 and stability < 5.0)
	p_weak = MagicMock()
	p_weak.id = "weak_engram"
	p_weak.payload = {"reinforcement_score": 0.09, "stability": 2.0, "immune": False, "last_recalled_at": time.time()}

	# Scroll side effect returns the points
	mock_client.scroll.return_value = ([p_immune, p_strong, p_weak], None)

	# Run the function
	run_rhizodb_washout_and_pruning(mock_mem_mgr)

	# Assertions:
	# - delete was called on weak_engram
	assert mock_client.delete.called
	args, kwargs = mock_client.delete.call_args
	points_selector = kwargs["points_selector"]
	assert "weak_engram" in points_selector.points
	assert "strong_engram" not in points_selector.points
	assert "immune_engram" not in points_selector.points

	# - batch_update_points was called on strong_engram
	assert mock_client.batch_update_points.called
	calls = mock_client.batch_update_points.call_args_list
	assert len(calls) > 0

	# Verify updated score on strong engram
	ops = calls[0][1]["update_operations"]
	strong_op = next((op for op in ops if op.set_payload.points == ["strong_engram"]), None)
	assert strong_op is not None
	assert strong_op.set_payload.payload["reinforcement_score"] == pytest.approx(0.762, abs=0.01)


def _point(point_id, score=0.8, stability=200.0, now=None):
	p = MagicMock()
	p.id = point_id
	p.payload = {"reinforcement_score": score, "stability": stability, "immune": False, "last_recalled_at": now if now is not None else time.time()}
	return p


def test_run_rhizodb_washout_paginates_all_pages(monkeypatch, tmp_path):
	monkeypatch.setattr(maint.cfg, "MEMORY_ENGINES", {"social_memories": "rhizodb"})
	monkeypatch.setattr(maint, "_washout_state_path", lambda: tmp_path / "washout.json")

	now = time.time()
	p1 = _point("p1", now=now)
	p2 = _point("p2", now=now)
	mock_mem_mgr, mock_client = _mock_manager(scroll_pages=[([p1], "page-2"), ([p2], None)])

	run_rhizodb_washout_and_pruning(mock_mem_mgr)

	assert mock_client.scroll.call_count == 2
	assert _updated_ids(mock_client) == ["p1", "p2"]


def test_run_rhizodb_washout_uses_config_gamma(monkeypatch, tmp_path):
	monkeypatch.setattr(maint.cfg, "MEMORY_ENGINES", {"social_memories": "rhizodb"})
	monkeypatch.setattr(maint.cfg, "RHIZODB_WASHOUT_GAMMA", 0.5)
	monkeypatch.setattr(maint, "_washout_state_path", lambda: tmp_path / "washout.json")

	p = _point("strong")
	mock_mem_mgr, mock_client = _mock_manager([p])

	run_rhizodb_washout_and_pruning(mock_mem_mgr)

	ops = mock_client.batch_update_points.call_args[1]["update_operations"]
	assert ops[0].set_payload.payload["reinforcement_score"] == pytest.approx(0.674, abs=0.01)


def test_run_rhizodb_washout_attenuates_repeated_runs(monkeypatch, tmp_path):
	state_path = tmp_path / "washout.json"
	monkeypatch.setattr(maint.cfg, "MEMORY_ENGINES", {"social_memories": "rhizodb"})
	monkeypatch.setattr(maint, "_washout_state_path", lambda: state_path)

	now = time.time()
	state_path.write_text(json.dumps({"social_memories": now - 43200.0}), encoding="utf-8")
	p = _point("strong", now=now)
	mock_mem_mgr, mock_client = _mock_manager([p])

	run_rhizodb_washout_and_pruning(mock_mem_mgr)

	gamma = 0.85 ** 0.5
	expected = round(gamma * 0.8 + (1.0 - gamma) * (200.0 / 365.0), 3)
	ops = mock_client.batch_update_points.call_args[1]["update_operations"]
	assert ops[0].set_payload.payload["reinforcement_score"] == pytest.approx(expected, abs=0.01)
	saved = json.loads(state_path.read_text(encoding="utf-8"))
	assert saved["social_memories"] > now - 60
