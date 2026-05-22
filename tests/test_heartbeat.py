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
	pulse._hygiene_ritual = AsyncMock()
	pulse._usp_ritual = AsyncMock()
	pulse._dream_ritual = AsyncMock()
	pulse._consolidation_ritual = AsyncMock()
	pulse._swarm_ritual = AsyncMock()
	pulse._lazarus_ritual = AsyncMock()
	pulse._resonance_ritual = AsyncMock()
	pulse._auto_heal_ritual = AsyncMock()
	pulse._thread_ritual = AsyncMock()
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


@pytest.mark.asyncio
@patch("red_pill.heartbeat.cfg")
async def test_maintenance_ritual_migraine(mock_cfg, pulse):
	mock_cfg.SIGNAL_MIGRAINE_VECTORS = 100
	mock_cfg.METABOLISM_STRATEGY = "CLASSIC"
	pulse.memory_mgr.client.count.return_value = MagicMock(count=150)
	await pulse._maintenance_ritual()
	pulse.memory_mgr.inject_signal.assert_any_call("semantic_migraine", intensity=6.0, signal_type="fatigue", source="HIPPOCAMPUS")

	pulse.memory_mgr.client.count.return_value = MagicMock(count=50)
	await pulse._maintenance_ritual()
	pulse.memory_mgr.evaporate_signals.assert_any_call("semantic_migraine")


@pytest.mark.asyncio
@patch("red_pill.heartbeat.cfg")
@patch.dict("sys.modules", {"psutil": MagicMock(sensors_temperatures=MagicMock(return_value={"coretemp": [MagicMock(current=90.0)]}))})
async def test_maintenance_ritual_fever(mock_cfg, pulse):
	mock_cfg.METABOLISM_STRATEGY = "CLASSIC"
	await pulse._maintenance_ritual()
	pulse.memory_mgr.inject_signal.assert_any_call("cpu_fever", intensity=7.0, signal_type="fever", source="HARDWARE")


@pytest.mark.asyncio
@patch("red_pill.heartbeat.cfg")
@patch("os.path.exists", return_value=True)
@patch("os.path.getmtime", return_value=0)
@patch("datetime.datetime")
async def test_maintenance_ritual_amnesia(mock_datetime, mock_mtime, mock_exists, mock_cfg, pulse):
	mock_cfg.INTERCEPTOR_ENABLED = True
	mock_cfg.SIGNAL_AMNESIA_HOURS = 24
	mock_cfg.METABOLISM_STRATEGY = "CLASSIC"
	mock_datetime.now.return_value = MagicMock(timestamp=MagicMock(return_value=3600 * 48))
	await pulse._maintenance_ritual()
	pulse.memory_mgr.inject_signal.assert_any_call("korsakoff_amnesia", intensity=5.5, signal_type="anxiety", source="HIPPOCAMPUS")
