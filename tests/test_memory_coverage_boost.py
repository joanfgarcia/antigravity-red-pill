from unittest.mock import MagicMock, patch

import pytest

from red_pill.identity import _load_identity
from red_pill.swarm.agents.agent import AgentMinion
from red_pill.utils.mood_profile import calculate_resonance_vector
from red_pill.utils.pre_heating_scorer import composite_score
from red_pill.utils.specs_adapter import SpecsAdapter
from red_pill.utils.telemetry_filter import calculate_entropy, filter_noise_from_turn, is_garbage
from red_pill.utils.uds_adapter import get_uds_opener


# 1. Boost identity.py
def test_load_identity_corrupted_exception():
	with patch("red_pill.identity.IDENTITY_FILE", "/nonexistent/invalid_path/identity.json"):
		# To trigger exception, we can patch os.path.exists to return True, but when opening, it raises Exception.
		with patch("os.path.exists", return_value=True), patch("builtins.open", side_effect=IOError("Permission denied")):
			assert _load_identity() == {}


def test_load_identity_file_missing():
	with patch("red_pill.identity.IDENTITY_FILE", "/nonexistent/path"):
		assert _load_identity() == {}


# 2. Boost utils/emotion.py
def test_get_emotions_model_failed_flag():
	import red_pill.utils.emotion as emotional_utils

	# Set model failed to True
	emotional_utils._model_failed = True
	try:
		assert emotional_utils.get_emotions("hello") == []
	finally:
		emotional_utils._model_failed = False


# 3. Boost utils/pre_heating_scorer.py
def test_composite_score_strategy_intensity():
	assert composite_score(8.5, "purple", 0.0, strategy="intensity") == 8.5


# 4. Boost utils/uds_adapter.py
def test_uds_opener_unix_open():
	opener = get_uds_opener()
	# Call open on a unix socket URL. It will call do_open and try UnixSocketHTTPConnection.connect.
	# It should try to connect and raise an error, which covers line 20.
	with pytest.raises(Exception):
		opener.open("unix://%2Ftmp%2Fnonexistent_socket.sock/path")


# 5. Boost swarm/agents/agent.py
@pytest.mark.asyncio
async def test_agent_minion_execute_with_backend():
	minion = AgentMinion()

	# Mock Result
	mock_result = MagicMock()
	mock_result.ok = True
	mock_result.response = "Hello response"
	mock_result.conversation_id = "conv_123"
	mock_result.error = None

	# Mock create_bridge
	with patch("red_pill.swarm.bridges.create_bridge") as mock_create_bridge:
		mock_bridge = MagicMock()
		mock_bridge.prompt.return_value = mock_result
		mock_create_bridge.return_value = mock_bridge

		res = await minion.execute("run some task", backend="claude", model="opus", effort="high", workspace="/tmp")

		assert res["status"] == "success"
		assert res["response"] == "Hello response"
		assert res["conversation_id"] == "conv_123"
		assert res["backend"] == "claude"
		assert mock_bridge.prompt.called
		mock_bridge.prompt.assert_called_with("run some task", model="opus", effort="high", cwd="/tmp", timeout=300)


@pytest.mark.asyncio
async def test_agent_minion_execute_default_backend():
	minion = AgentMinion()

	mock_result = MagicMock()
	mock_result.ok = False
	mock_result.response = "Failed response"
	mock_result.conversation_id = "conv_none"
	mock_result.error = "Timeout"

	# Mock create_cascade_bridge
	with patch("red_pill.swarm.bridges.create_cascade_bridge") as mock_create_cascade_bridge:
		mock_bridge = MagicMock()
		mock_bridge.prompt.return_value = mock_result
		mock_create_cascade_bridge.return_value = mock_bridge

		res = await minion.execute("run background task")

		assert res["status"] == "failed"
		assert res["response"] == "Failed response"
		assert res["error"] == "Timeout"
		assert res["backend"] == "config"
		assert mock_bridge.prompt.called


@pytest.mark.asyncio
async def test_agent_minion_execute_exception():
	minion = AgentMinion()

	with patch("red_pill.swarm.bridges.create_bridge", side_effect=ValueError("Invalid backend")):
		res = await minion.execute("run background task", backend="nonexistent")
		assert res["status"] == "error"
		assert "Invalid backend" in res["error"]


# 6. Boost utils/mood_profile.py
def test_mood_profile_max_scroll_warning():
	mock_mgr = MagicMock()
	mock_mgr.client.scroll.return_value = ([], "some_offset")

	with patch("red_pill.utils.mood_profile.cfg") as mock_cfg:
		mock_cfg.MOOD_PROFILE_MAX_SCROLL = 1
		mock_cfg.DEFAULT_COLOR = "gray"
		with patch("red_pill.utils.mood_profile.logger") as mock_logger:
			calculate_resonance_vector(mock_mgr, 3600.0)
			assert mock_logger.warning.called
			args, kwargs = mock_logger.warning.call_args
			assert "PERF-001" in args[0]


# 7. Boost utils/specs_adapter.py
def test_specs_adapter_get_fire_intents_checkpoint_none(tmp_path):
	adapter = SpecsAdapter(str(tmp_path))
	assert adapter.get_fire_intents() == []


# 8. Boost utils/telemetry_filter.py
def test_telemetry_filter_entropy_empty():
	assert calculate_entropy("") == 0.0


def test_telemetry_filter_is_garbage_hits():
	assert is_garbage("passed in some tests, got a PASS") is True


def test_telemetry_filter_is_garbage_low_entropy():
	assert is_garbage("a" * 200) is True


def test_telemetry_filter_filter_noise_empty():
	assert filter_noise_from_turn("") == ""


def test_telemetry_filter_filter_noise_all_garbage():
	assert filter_noise_from_turn("assert 0 == 1\nAssertionError:") == ""
