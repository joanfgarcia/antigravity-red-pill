import math

from red_pill.affect import RhizoDBEngine, get_memory_engine


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


def test_get_memory_engine_factory():
	engine = get_memory_engine("rhizodb")
	assert isinstance(engine, RhizoDBEngine)
