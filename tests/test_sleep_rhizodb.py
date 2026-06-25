import time
from unittest.mock import MagicMock

import pytest

from red_pill.metabolism.sleep import run_rhizodb_washout_and_pruning


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
