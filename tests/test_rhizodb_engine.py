import math
import time
from datetime import datetime, timezone

import pytest

from red_pill.affect import BayesianEngine, FSRSEngine, RhizoDBEngine, get_memory_engine
from red_pill.utils.affect import calculate_fsrs_new_stability, calculate_fsrs_retrievability


# 1. RhizoDB Engine Tests
def test_rhizodb_engine_initialization():
	engine = RhizoDBEngine()
	assert engine.deletion_threshold == 0.05
	assert engine.S_max == 365.0
	assert engine.eta == 0.1
	assert math.isclose(engine.lambda_constant, -math.log(0.9))


def test_rhizodb_reinforcement():
	engine = RhizoDBEngine()
	# Initial score 0.5, stability 10.0, increment 0.5
	payload = {"reinforcement_score": 0.5, "stability": 10.0}
	updates = engine.calculate_reinforcement(payload, increment=0.5)

	# a_v(t+1) = a_v(t) + (1.0 - a_v(t)) * alpha
	# = 0.5 + 0.5 * 0.5 = 0.75
	assert updates["reinforcement_score"] == 0.75

	# s_v(t+1) = s_v(t) + eta * alpha * (S_max - s_v(t))
	# = 10.0 + 0.1 * 0.5 * (365.0 - 10.0) = 10.0 + 0.05 * 355.0 = 10.0 + 17.75 = 27.75
	assert updates["stability"] == 27.75


def test_rhizodb_reinforcement_saturation():
	engine = RhizoDBEngine(S_max=365.0)
	# High activation and stability
	payload = {"reinforcement_score": 0.99, "stability": 360.0}
	updates = engine.calculate_reinforcement(payload, increment=1.0)

	# Activation should approach 1.0 but not exceed it
	assert updates["reinforcement_score"] == 1.0

	# Stability should approach 365.0 but not exceed it
	# 360.0 + 0.1 * 1.0 * (365.0 - 360.0) = 360.0 + 0.5 = 360.5
	assert updates["stability"] == 360.5


def test_rhizodb_lazy_decay():
	engine = RhizoDBEngine()
	import time

	now = time.time()
	one_day = 86400.0

	payload = {"reinforcement_score": 1.0, "stability": 10.0, "last_recalled_at": now - 10.0 * one_day}

	# dt = 10 days, S = 10 days
	# a(10) = 1.0 * e^(-lambda * 10 / 10) = e^(-lambda) = e^(ln(0.9)) = 0.9
	decay_updates = engine.calculate_lazy_decay(payload, now)
	assert decay_updates["reinforcement_score"] == 0.9


def test_rhizodb_lazy_decay_deletion():
	engine = RhizoDBEngine(deletion_threshold=0.5)
	import time

	now = time.time()
	one_day = 86400.0

	# S = 10 days, dt = 10 days. Decay brings it to 0.9.
	# With threshold = 0.5, 0.9 is greater, so no delete.
	payload = {"reinforcement_score": 1.0, "stability": 10.0, "last_recalled_at": now - 10.0 * one_day}
	decay_updates = engine.calculate_lazy_decay(payload, now)
	assert not decay_updates.get("_delete")

	# Now let's decay enough to drop below 0.5
	# e.g., dt = 100 days
	payload_old = {"reinforcement_score": 1.0, "stability": 10.0, "last_recalled_at": now - 100.0 * one_day}
	decay_updates_old = engine.calculate_lazy_decay(payload_old, now)
	assert decay_updates_old.get("_delete") is True


# 2. FSRSEngine Tests
def test_fsrs_engine_lazy_decay():
	engine = FSRSEngine(deletion_threshold=0.05)
	import time

	now = time.time()

	# stability <= 0
	payload_bad = {"reinforcement_score": 0.8, "stability": -1.0, "last_recalled_at": now - 100}
	res = engine.calculate_lazy_decay(payload_bad, now)
	assert res.get("_delete") is True

	# normal decay, not below threshold
	payload_normal = {"reinforcement_score": 0.8, "stability": 10.0, "last_recalled_at": now - 10.0 * 86400.0}
	res = engine.calculate_lazy_decay(payload_normal, now)
	# R = e^(ln(0.9)*10/10) = 0.9. new_score = 0.8 * 0.9 = 0.72
	assert res["reinforcement_score"] == 0.72

	# decay with no time passed
	res_none = engine.calculate_lazy_decay(payload_normal, now - 10.0 * 86400.0)
	assert res_none == {}


def test_fsrs_engine_reinforcement():
	engine = FSRSEngine()
	payload = {"reinforcement_score": 0.5, "stability": 10.0}
	res = engine.calculate_reinforcement(payload, increment=0.2)
	assert res["reinforcement_score"] == 0.7
	assert res["stability"] == 14.0


# 3. BayesianEngine Tests
def test_bayesian_engine_lazy_decay():
	engine = BayesianEngine(deletion_threshold=0.5)
	import time

	now = time.time()

	payload = {"utility_alpha": 5.0, "utility_beta": 1.0, "last_recalled_at": now - 10.0 * 86400.0}
	# time passed = 10 days. new_beta = 1.0 + ln(1 + 10) = 1.0 + 2.3979 = 3.3979
	# utility = 5.0 / (5.0 + 3.3979) = 0.5954
	res = engine.calculate_lazy_decay(payload, now)
	assert res["reinforcement_score"] == pytest.approx(0.5954, abs=0.01)

	# delete threshold triggered
	payload_bad = {"utility_alpha": 1.0, "utility_beta": 5.0, "last_recalled_at": now - 10.0 * 86400.0}
	# utility = 1.0 / (1.0 + 5.0 + ln(11)) = 1.0 / (8.39) = 0.119
	res_bad = engine.calculate_lazy_decay(payload_bad, now)
	assert res_bad.get("_delete") is True


def test_bayesian_engine_reinforcement():
	engine = BayesianEngine()
	payload = {"utility_alpha": 2.0, "utility_beta": 2.0, "content": "normal text"}
	res = engine.calculate_reinforcement(payload, increment=0.5)
	# new_alpha = 2.0 + (0.5 * 5) = 4.5
	# new_beta = max(1.0, 2.0 - (0.5 * 2)) = 1.0
	# utility = 4.5 / (4.5 + 1.0) = 0.818
	assert res["utility_alpha"] == 4.5
	assert res["utility_beta"] == 1.0
	assert res["reinforcement_score"] == 0.818


def test_bayesian_engine_reinforcement_garbage():
	engine = BayesianEngine()
	# content matching garbage (e.g. low entropy or noise)
	# calculate_entropy for repetitive content is low (< 3.2)
	payload = {"utility_alpha": 2.0, "utility_beta": 2.0, "content": "aaaaa aaaaa aaaaa aaaaa aaaaa aaaaa"}
	res = engine.calculate_reinforcement(payload, increment=0.5)
	# Should trigger anti-noise gate and increase beta by 1.0 without alpha change
	assert "utility_alpha" not in res
	assert res["utility_beta"] == 3.0


# 4. FSRS Utils Tests
def test_fsrs_utils_retrievability():
	# stability <= 0
	assert calculate_fsrs_retrievability(0.0, 100.0) == 0.0
	assert calculate_fsrs_retrievability(-5.0, 100.0) == 0.0

	# days_passed <= 0
	assert calculate_fsrs_retrievability(10.0, -100.0) == 1.0

	# normal
	# days = 10, stability = 10 => R = e^(ln(0.9)*1) = 0.9
	assert calculate_fsrs_retrievability(10.0, 10.0 * 86400.0) == pytest.approx(0.9)


def test_fsrs_utils_new_stability():
	# is_success = False
	assert calculate_fsrs_new_stability(10.0, 5.0, 0.9, is_success=False) == 3.0

	# current_stability <= 0
	assert calculate_fsrs_new_stability(0.0, 5.0, 0.9, is_success=True) == 1.0

	# normal success
	# stability = 10, difficulty = 5.0, R = 0.9
	# gain = 10 * e^(0.5 * (1 - 0.9)) * (11 - 5.0) / 10 = 10 * e^0.05 * 0.6 = 6.3078
	# new_stability = 10.0 + 6.3078 = 16.3078
	assert calculate_fsrs_new_stability(10.0, 5.0, 0.9, is_success=True) == pytest.approx(16.3078, abs=0.01)


# 5. Factory tests
def test_get_memory_engine_factory():
	assert isinstance(get_memory_engine("rhizodb"), RhizoDBEngine)
	assert isinstance(get_memory_engine("bayesian"), BayesianEngine)
	assert isinstance(get_memory_engine("fsrs"), FSRSEngine)
	assert isinstance(get_memory_engine("fsrs_real"), FSRSEngine)
	assert isinstance(get_memory_engine("invalid_engine_name"), FSRSEngine)


def test_abstract_memory_engine_methods():
	from red_pill.affect import MemoryEngine

	# Directly invoke the abstract methods to execute their pass statements
	MemoryEngine.calculate_lazy_decay(None, {}, 0.0)
	MemoryEngine.calculate_reinforcement(None, {}, 0.0)


# 6. Payload hardening (NaN/Inf, corrupt/ISO/millisecond timestamps)
def test_rhizodb_nonfinite_fields_fall_back_to_defaults():
	engine = RhizoDBEngine()
	now = time.time()
	payload = {
		"reinforcement_score": float("nan"),
		"stability": float("inf"),
		"last_recalled_at": now - 10.0 * 86400.0,
	}
	updates = engine.calculate_lazy_decay(payload, now)
	# NaN score -> 1.0, Inf stability -> 1.0 day: e^(-lambda * 10/1)
	assert updates["reinforcement_score"] == pytest.approx(math.exp(-engine.lambda_constant * 10.0), abs=0.01)


def test_rhizodb_timestamps_iso_numeric_string_and_milliseconds():
	engine = RhizoDBEngine()
	now = time.time()
	base = {"reinforcement_score": 1.0, "stability": 10.0}
	iso = datetime.fromtimestamp(now - 10.0 * 86400.0, tz=timezone.utc).isoformat()
	ms = (now - 10.0 * 86400.0) * 1000.0
	for stamp in (iso, ms, str(now - 10.0 * 86400.0)):
		updates = engine.calculate_lazy_decay({**base, "last_recalled_at": stamp}, now)
		assert updates["reinforcement_score"] == pytest.approx(0.9, abs=0.01)


def test_rhizodb_corrupt_timestamp_does_not_crash():
	engine = RhizoDBEngine()
	now = time.time()
	base = {"reinforcement_score": 1.0, "stability": 10.0}
	assert engine.calculate_lazy_decay({**base, "last_recalled_at": "not-a-date"}, now) == {}
	assert engine.calculate_lazy_decay({**base, "last_recalled_at": None}, now) == {}
	assert engine.calculate_lazy_decay({**base, "last_recalled_at": True}, now) == {}


def test_rhizodb_negative_stability_is_forgotten():
	engine = RhizoDBEngine()
	now = time.time()
	updates = engine.calculate_lazy_decay({"reinforcement_score": 0.8, "stability": -5.0, "last_recalled_at": now - 86400.0}, now)
	assert updates.get("_delete") is True


def test_rhizodb_curated_score_above_one_is_preserved():
	engine = RhizoDBEngine()
	now = time.time()
	updates = engine.calculate_lazy_decay({"reinforcement_score": 5.0, "stability": 10.0, "last_recalled_at": now - 10.0 * 86400.0}, now)
	assert updates["reinforcement_score"] == pytest.approx(4.5, abs=0.01)


def test_rhizodb_reinforce_nonfinite_inputs():
	engine = RhizoDBEngine()
	updates = engine.calculate_reinforcement({"reinforcement_score": float("nan"), "stability": float("nan")}, increment=0.5)
	# score NaN -> 1.0 (nothing left to reinforce), stability NaN -> 1.0 day
	assert updates["reinforcement_score"] == 1.0
	assert updates["stability"] == pytest.approx(19.2, abs=0.01)


def test_fsrs_nan_stability_decays_instead_of_immortal():
	engine = FSRSEngine()
	now = time.time()
	updates = engine.calculate_lazy_decay({"reinforcement_score": 0.8, "stability": float("nan"), "last_recalled_at": now - 10.0 * 86400.0}, now)
	assert updates["reinforcement_score"] == pytest.approx(0.8 * math.exp(math.log(0.9) * 10.0), abs=0.01)


def test_bayesian_nonfinite_inputs_fall_back():
	engine = BayesianEngine()
	now = time.time()
	updates = engine.calculate_lazy_decay({"utility_alpha": float("nan"), "utility_beta": float("inf"), "last_recalled_at": now - 86400.0}, now)
	# alpha NaN -> 1.0, beta Inf -> 1.0: beta_new = 1 + ln(2) -> utility = 1 / (2 + ln(2))
	assert updates["reinforcement_score"] == pytest.approx(0.371, abs=0.01)


def test_bayesian_zero_prior_does_not_divide_by_zero():
	engine = BayesianEngine()
	now = time.time()
	updates = engine.calculate_lazy_decay({"utility_alpha": 0.0, "utility_beta": 0.0, "last_recalled_at": now}, now)
	assert updates.get("_delete") is True
