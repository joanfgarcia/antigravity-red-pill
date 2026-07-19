"""
P0 recall fix: Bayesian lazy-decay threshold calibration.

The BayesianEngine deletion threshold was 0.5 — exactly the mean of the uniform
prior Beta(1,1). Every engram without reinforcement history had utility
alpha/(alpha+beta) = 0.5 <= 0.5 and was marked _delete at t=0: born dead.
Live measurement (2026-07-18, work_memories, 16512 points) showed 99.0% of the
collection hidden from recall, including 8872 immune engrams.

The threshold must sit strictly below the prior mean so that an engram starts
alive and only erodes after sustained non-recall (~19 days at 0.2).
"""

from red_pill.affect import BayesianEngine, get_memory_engine

DAY = 86400.0
NOW = 1_700_000_000.0


def _payload(alpha=1.0, beta=1.0, age_days=0.0):
	return {
		"utility_alpha": alpha,
		"utility_beta": beta,
		"last_recalled_at": NOW - age_days * DAY,
		"reinforcement_score": 0.5,
		"content": "prueba de calibracion del decaimiento",
	}


class TestBayesianThresholdCalibration:
	def test_threshold_below_prior_mean(self):
		"""The deletion threshold must be strictly below E[Beta(1,1)] = 0.5."""
		assert BayesianEngine().deletion_threshold < 0.5

	def test_fresh_prior_engram_is_alive(self):
		"""Regression: an engram with no reinforcement history must NOT be born dead."""
		updates = BayesianEngine().calculate_lazy_decay(_payload(), current_time=NOW)
		assert not updates.get("_delete")

	def test_prior_engram_survives_two_weeks_unrecalled(self):
		"""utility = 1/(2+ln(15)) ~= 0.212 > 0.2 -> still alive."""
		updates = BayesianEngine().calculate_lazy_decay(_payload(age_days=14.0), current_time=NOW)
		assert not updates.get("_delete")
		assert updates.get("reinforcement_score", 1.0) > 0.2

	def test_prior_engram_erodes_after_a_month_unrecalled(self):
		"""utility = 1/(2+ln(31)) ~= 0.183 <= 0.2 -> eligible for forgetting."""
		updates = BayesianEngine().calculate_lazy_decay(_payload(age_days=30.0), current_time=NOW)
		assert updates.get("_delete") is True

	def test_single_recall_rescues_a_prior_engram(self):
		"""One reinforcement (alpha += 5*increment) must push utility well above threshold."""
		engine = BayesianEngine()
		reinforced = engine.calculate_reinforcement(_payload(), increment=0.1)
		payload = _payload(age_days=14.0)
		payload.update(reinforced)
		updates = engine.calculate_lazy_decay(payload, current_time=NOW)
		assert not updates.get("_delete")

	def test_missing_bayesian_fields_default_to_alive(self):
		"""Legacy engrams without utility_alpha/utility_beta fall back to the prior — alive."""
		updates = BayesianEngine().calculate_lazy_decay({"last_recalled_at": NOW, "reinforcement_score": 1.0}, current_time=NOW)
		assert not updates.get("_delete")

	def test_factory_returns_calibrated_engine(self):
		assert get_memory_engine("bayesian").deletion_threshold < 0.5


class TestFSRSStillSane:
	def test_fresh_fsrs_engram_is_alive(self):
		engine = get_memory_engine("fsrs_real")
		updates = engine.calculate_lazy_decay({"last_recalled_at": NOW, "reinforcement_score": 1.0, "stability": 1.0}, current_time=NOW)
		assert not updates.get("_delete")
