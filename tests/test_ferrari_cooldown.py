import asyncio
import importlib
from unittest.mock import MagicMock, patch
import pytest

from red_pill.interceptors import _05_cognitive_router_state as _cr_state

# Import digit-starting modules dynamically
router_mod = importlib.import_module("red_pill.interceptors.05_cognitive_router")
tone_mod = importlib.import_module("red_pill.interceptors.06_tone_adapter")

CognitiveRouterPlugin = router_mod.CognitiveRouterPlugin
ToneAdapterPlugin = tone_mod.ToneAdapterPlugin


@pytest.fixture(autouse=True)
def reset_router_state():
	"""Resets the shared router state before and after each test."""
	_cr_state._casual_mode_active = False
	_cr_state._consecutive_non_work_turns = 0
	_cr_state._last_router_state = None
	_cr_state._last_tone_state = None
	yield
	_cr_state._casual_mode_active = False
	_cr_state._consecutive_non_work_turns = 0
	_cr_state._last_router_state = None
	_cr_state._last_tone_state = None


def test_cooldown_decay_logic():
	"""Tests the 'engine braking' (freno de motor) turn-decay logic."""
	casual_kws = ["relax", "charlemos"]

	# Turn 1: Explicit work keyword triggers work mode (casual active = False)
	_cr_state.register_turn("implementa el router", casual_kws)
	assert not _cr_state.is_casual_active()
	assert _cr_state._consecutive_non_work_turns == 0

	# Turn 2: Non-work prompt (1st turn of inertia) -> remains in work mode
	_cr_state.register_turn("qué opinas de esto", casual_kws)
	assert not _cr_state.is_casual_active()
	assert _cr_state._consecutive_non_work_turns == 1

	# Turn 3: Second consecutive non-work prompt -> decays to casual mode
	_cr_state.register_turn("sí, suena interesante", casual_kws)
	assert _cr_state.is_casual_active()
	assert _cr_state._consecutive_non_work_turns == 0


def test_explicit_casual_keywords():
	"""Tests that explicit casual keywords trigger casual mode immediately."""
	casual_kws = ["relax", "charlemos"]

	_cr_state.register_turn("implementa el router", casual_kws)
	assert not _cr_state.is_casual_active()

	# Explicit casual keyword -> instant casual mode
	_cr_state.register_turn("vamos a charlemos un rato", casual_kws)
	assert _cr_state.is_casual_active()


def test_work_keywords_precedence():
	"""Tests that work keywords immediately override casual mode."""
	casual_kws = ["relax", "charlemos"]

	# Set casual mode active
	_cr_state.set_casual(True)
	assert _cr_state.is_casual_active()

	# User sends a work keyword -> overrides casual mode immediately
	_cr_state.register_turn("arregla el bug ahora", casual_kws)
	assert not _cr_state.is_casual_active()
	assert _cr_state._consecutive_non_work_turns == 0


@pytest.mark.asyncio
async def test_cognitive_router_plugin_transitions():
	"""Tests the CognitiveRouterPlugin execution and transition emission."""
	p = CognitiveRouterPlugin()
	assert p.is_enabled

	# Configure config mock for casual keywords
	cfg_mock = MagicMock(CASUAL_OVERRIDE_KEYWORDS=["relax", "charlemos"], COGNITIVE_ROUTER_ENABLED=True)

	with (
		patch("red_pill.config.get_config", return_value=cfg_mock),
		patch.object(router_mod, "get_current_sync_state", return_value={"mood": "purple"}),
	):
		# Turn 1: work keyword -> triggers transition to purple, returns directive
		res1 = await p.execute("trabaja en el commit")
		assert "COGNITIVE ROUTER" in res1
		assert "OPERATOR_COLOR: PURPLE" in res1

		# Turn 2: same state, no transition -> returns empty string (silence)
		res2 = await p.execute("ejecuta los tests")
		assert res2 == ""

		# Turn 3: 1st non-work turn -> no transition yet (still purple), returns empty
		res3 = await p.execute("hola")
		assert res3 == ""

		# Turn 4: 2nd non-work turn -> decays to casual, state transitions, returns empty since casual override emits nothing
		res4 = await p.execute("qué tal todo")
		assert res4 == ""
		assert _cr_state.is_casual_active()

		# Turn 5: work keyword -> transitions back to purple, returns directive
		res5 = await p.execute("despliega la app")
		assert "COGNITIVE ROUTER" in res5
		assert "OPERATOR_COLOR: PURPLE" in res5


@pytest.mark.asyncio
async def test_tone_adapter_plugin_transitions():
	"""Tests the ToneAdapterPlugin execution and transition emission."""
	p = ToneAdapterPlugin()
	assert p.is_enabled

	# Configure config mock for casual keywords
	cfg_mock = MagicMock(CASUAL_OVERRIDE_KEYWORDS=["relax", "charlemos"], TONE_ADAPTER_ENABLED=True)

	with (
		patch("red_pill.config.get_config", return_value=cfg_mock),
		patch.object(tone_mod, "get_current_sync_state", return_value={"mood": "purple"}),
	):
		# Turn 1: work keyword -> transitions to purple
		_cr_state.register_turn("trabaja en el commit", ["relax", "charlemos"])
		res1 = await p.execute("trabaja en el commit")
		assert "TONE ADAPTER" in res1
		assert "TONE_DIRECTIVE:" in res1

		# Turn 2: same state -> returns empty (silence)
		_cr_state.register_turn("ejecuta los tests", ["relax", "charlemos"])
		res2 = await p.execute("ejecuta los tests")
		assert res2 == ""

		# Turn 3: 1st non-work turn -> no transition, returns empty
		_cr_state.register_turn("hola", ["relax", "charlemos"])
		res3 = await p.execute("hola")
		assert res3 == ""

		# Turn 4: 2nd non-work turn -> decays to casual, returns empty
		_cr_state.register_turn("qué tal todo", ["relax", "charlemos"])
		res4 = await p.execute("qué tal todo")
		assert res4 == ""
		assert _cr_state.is_casual_active()

		# Turn 5: work keyword -> transitions back to purple, returns directive
		_cr_state.register_turn("despliega la app", ["relax", "charlemos"])
		res5 = await p.execute("despliega la app")
		assert "TONE ADAPTER" in res5
		assert "TONE_DIRECTIVE:" in res5
