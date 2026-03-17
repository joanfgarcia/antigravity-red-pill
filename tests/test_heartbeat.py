import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from red_pill.heartbeat import LazarusPulse


@pytest.fixture
def pulse():
	mem_mgr = MagicMock()
	soul_mgr = MagicMock()
	p = LazarusPulse(mem_mgr, soul_mgr)
	return p


def test_pulse_sync_lifecycle(pulse):
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		mock_cfg.PULSE_ENABLED = False
		pulse.start()
		assert not pulse._running
		mock_cfg.PULSE_ENABLED = True
		with patch("threading.Thread"):
			pulse.start()
			assert pulse._running
			pulse.start()
			pulse._loop = MagicMock()
			pulse.stop()
			assert not pulse._running
			pulse.stop()


@pytest.mark.asyncio
async def test_pulse_cycle_logic(pulse):
	pulse._maintenance_ritual = AsyncMock()
	pulse._usp_ritual = AsyncMock()
	pulse._dream_ritual = AsyncMock()
	pulse._running = True
	with patch("asyncio.sleep", AsyncMock()) as mock_sleep:

		async def stop_loop(*args):
			pulse._running = False
			return None

		mock_sleep.side_effect = stop_loop
		await pulse._pulse_cycle()
		assert pulse._maintenance_ritual.called
	pulse._running = True
	with patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
		await pulse._pulse_cycle()
		assert pulse._running
	pulse._running = True
	pulse._maintenance_ritual = AsyncMock(side_effect=Exception("Arrythmia"))
	with patch("asyncio.sleep", AsyncMock()) as mock_sleep:

		async def stop_after_error(wait_time):
			if wait_time == 60:
				pulse._running = False
			return None

		mock_sleep.side_effect = stop_after_error
		await pulse._pulse_cycle()


@pytest.mark.asyncio
async def test_ritual_failures_final(pulse):
	pulse.memory_mgr.client.get_collections.side_effect = Exception("DB Down")
	await pulse._maintenance_ritual()
	pulse.memory_mgr.client.get_collections.side_effect = None
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		mock_cfg.METABOLISM_STRATEGY = "LAZY"
		with patch("asyncio.to_thread", AsyncMock(side_effect=Exception("TTL Err"))):
			await pulse._maintenance_ritual()
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		type(mock_cfg).METABOLISM_STRATEGY = PropertyMock(side_effect=Exception("Hard Fail"))
		await pulse._maintenance_ritual()
	with patch("asyncio.to_thread", AsyncMock(side_effect=Exception("Dream Individual Fail"))):
		await pulse._dream_ritual()
	with patch("red_pill.heartbeat.logger.info", side_effect=Exception("Dream Hard Fail")):
		await pulse._dream_ritual()


def test_event_loop_coverage(pulse):
	mock_loop = MagicMock()
	with patch("asyncio.new_event_loop", return_value=mock_loop), patch("asyncio.set_event_loop"):
		pulse._run_event_loop()
		assert mock_loop.run_forever.called


@pytest.mark.asyncio
async def test_usp_ritual_success(pulse):
	"""Covers heartbeat.py lines 119-130 — successful USP refresh."""
	mock_usp = {"last_3d": {"orange": 0.7, "blue": 0.3}, "interaction_count": 42}
	with patch("asyncio.to_thread", AsyncMock(return_value=mock_usp)):
		await pulse._usp_ritual()


@pytest.mark.asyncio
async def test_usp_ritual_failure(pulse):
	"""Covers heartbeat.py lines 132-133 — USP ritual exception."""
	with patch("asyncio.to_thread", AsyncMock(side_effect=Exception("USP Fail"))):
		await pulse._usp_ritual()


@pytest.mark.asyncio
async def test_consolidation_ritual_failure(pulse):
	"""Covers heartbeat.py lines 166-167."""
	with patch("asyncio.to_thread", AsyncMock(side_effect=Exception("Consol Fail"))):
		await pulse._consolidation_ritual()


@pytest.mark.asyncio
async def test_swarm_ritual_with_messages(pulse):
	"""Covers heartbeat.py lines 186-190 — swarm with incoming messages."""
	mock_messages = [{"sender": "Nova", "message": "Hello", "intent": "gossip"}]
	with patch("red_pill.heartbeat.SwarmMessagingSkill"):
		with patch("asyncio.to_thread", AsyncMock(side_effect=[mock_messages, None])):
			await pulse._swarm_ritual()


@pytest.mark.asyncio
async def test_swarm_ritual_failure(pulse):
	"""Covers swarm exception path."""
	with patch("red_pill.heartbeat.SwarmMessagingSkill", side_effect=Exception("Swarm init fail")):
		await pulse._swarm_ritual()


@pytest.mark.asyncio
async def test_lazarus_ritual_disabled(pulse):
	"""Covers heartbeat.py line 211 — LAZARUS_SYNC_ENABLED=False."""
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		mock_cfg.LAZARUS_SYNC_ENABLED = False
		await pulse._lazarus_ritual()


@pytest.mark.asyncio
async def test_lazarus_ritual_failure(pulse):
	"""Covers heartbeat.py lines 226-240."""
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		mock_cfg.LAZARUS_SYNC_ENABLED = True
		mock_cfg.OPERATOR_DISPLAY_NAME = "test"
		with patch.dict("sys.modules", {"red_pill.hive": MagicMock(HiveMind=MagicMock(side_effect=Exception("Hive fail")))}):
			await pulse._lazarus_ritual()


@pytest.mark.asyncio
async def test_resonance_ritual_disabled(pulse):
	"""Covers heartbeat.py line 249 — RESONANCE_ENABLED=False."""
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		mock_cfg.RESONANCE_ENABLED = False
		await pulse._resonance_ritual()


@pytest.mark.asyncio
async def test_resonance_ritual_failure(pulse):
	"""Covers heartbeat.py lines 266-269."""
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		mock_cfg.RESONANCE_ENABLED = True
		mock_cfg.OPERATOR_DISPLAY_NAME = "test"
		mock_cfg.VECTOR_SIZE = 384
		with patch.dict("sys.modules", {"red_pill.swarm.resonance": MagicMock(ResonanceObserver=MagicMock(side_effect=Exception("Resonance fail")))}):
			await pulse._resonance_ritual()
