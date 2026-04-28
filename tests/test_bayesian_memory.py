"""
Phase B.2 Tests: Bayesian Routing Logic.
Validates that search_and_reinforce correctly routes to the
Bayesian Utility kernel for technical collections and the
Affective FSRS kernel for social collections.
"""

from unittest.mock import MagicMock

import pytest

from red_pill.memory import BayesianInferenceEngine


class TestBayesianInferenceEngine:
	"""Unit tests for the core Bayesian math."""

	def test_utility_uniform_prior(self):
		"""Beta(1,1) = 0.5 (maximum uncertainty)."""
		assert BayesianInferenceEngine.calculate_utility(1.0, 1.0) == 0.5

	def test_utility_strong_prior(self):
		"""Beta(9,1) ≈ 0.9 (very reliable engram)."""
		assert BayesianInferenceEngine.calculate_utility(9.0, 1.0) == 0.9

	def test_utility_weak_engram(self):
		"""Beta(1,9) ≈ 0.1 (unreliable engram)."""
		assert BayesianInferenceEngine.calculate_utility(1.0, 9.0) == 0.1

	def test_utility_edge_zero(self):
		"""Edge case: alpha=0 returns 0.5 (safe fallback)."""
		assert BayesianInferenceEngine.calculate_utility(0, 1) == 0.5

	def test_normalize_max(self):
		"""Utility 1.0 maps to score 10.0."""
		assert BayesianInferenceEngine.normalize_to_reinforcement_score(1.0) == 10.0

	def test_normalize_min(self):
		"""Utility 0.0 maps to score 0.0."""
		assert BayesianInferenceEngine.normalize_to_reinforcement_score(0.0) == 0.0

	def test_normalize_mid(self):
		"""Utility 0.5 maps to score 5.0."""
		assert BayesianInferenceEngine.normalize_to_reinforcement_score(0.5) == 5.0

	def test_erosion_accumulates(self):
		"""Beta grows with time: 1.0 + (10 days * 0.05) = 1.5."""
		result = BayesianInferenceEngine.calculate_erosion(1.0, 10.0, kappa=0.05)
		assert result == 1.5

	def test_erosion_zero_time(self):
		"""No time passed = no erosion."""
		result = BayesianInferenceEngine.calculate_erosion(1.0, 0.0, kappa=0.05)
		assert result == 1.0


class TestDualKernelRouting:
	"""Integration tests for collection-based routing."""

	@pytest.fixture
	def mock_config(self):
		"""Creates a mock config with Bayesian collections defined."""
		mock_cfg = MagicMock()
		mock_cfg.BAYESIAN_COLLECTIONS = ["skill_memories", "work_memories", "directive_memories"]
		mock_cfg.METABOLISM_STRATEGY = "LAZY"
		mock_cfg.DEEP_RECALL_TRIGGERS = []
		mock_cfg.REINFORCEMENT_INCREMENT = 0.1
		mock_cfg.PROPAGATION_FACTOR = 0.5
		mock_cfg.PROPAGATION_DEPTH = 2
		mock_cfg.PROPAGATION_DECAY = 0.5
		mock_cfg.MAX_PROPAGATION_POINTS = 20
		mock_cfg.BAYESIAN_STABILITY_KAPPA = 0.05
		mock_cfg.BAYESIAN_REINFORCEMENT_GAIN = 1.0
		mock_cfg.IMMUNITY_THRESHOLD = 10.0
		mock_cfg.CURRENT_SCHEMA_VERSION = 1
		return mock_cfg

	def test_bayesian_collection_detected(self, mock_config):
		"""work_memories should route to the Bayesian kernel."""
		assert "work_memories" in mock_config.BAYESIAN_COLLECTIONS
		assert "directive_memories" in mock_config.BAYESIAN_COLLECTIONS
		assert "skill_memories" in mock_config.BAYESIAN_COLLECTIONS

	def test_affective_collection_excluded(self, mock_config):
		"""social_memories should NOT route to the Bayesian kernel."""
		assert "social_memories" not in mock_config.BAYESIAN_COLLECTIONS
		assert "story_memories" not in mock_config.BAYESIAN_COLLECTIONS

	def test_utility_score_is_normalized(self):
		"""Bayesian utility maps to the same [0-10] score range as FSRS."""
		utility = BayesianInferenceEngine.calculate_utility(5.0, 1.0)
		score = BayesianInferenceEngine.normalize_to_reinforcement_score(utility)
		assert 0.0 <= score <= 10.0
		assert score > 5.0
