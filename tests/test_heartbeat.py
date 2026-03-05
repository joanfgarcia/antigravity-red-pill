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
			pulse.start()  # Hits 31

			pulse._loop = MagicMock()
			pulse.stop()  # Hits 44
			assert not pulse._running
			pulse.stop()  # Hits 41


@pytest.mark.asyncio
async def test_pulse_cycle_logic(pulse):
	pulse._maintenance_ritual = AsyncMock()
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
		await pulse._pulse_cycle()  # Hits 70
		assert pulse._running

	pulse._running = True
	pulse._maintenance_ritual = AsyncMock(side_effect=Exception("Arrythmia"))
	with patch("asyncio.sleep", AsyncMock()) as mock_sleep:

		async def stop_after_error(wait_time):
			if wait_time == 60:
				pulse._running = False
			return None

		mock_sleep.side_effect = stop_after_error
		await pulse._pulse_cycle()  # Hits 72-73


@pytest.mark.asyncio
async def test_ritual_failures_final(pulse):
	# db error (88)
	pulse.memory_mgr.client.get_collections.side_effect = Exception("DB Down")
	await pulse._maintenance_ritual()

	# absence guard error (100)
	pulse.memory_mgr.client.get_collections.side_effect = None
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		mock_cfg.METABOLISM_STRATEGY = "LAZY"
		with patch("asyncio.to_thread", AsyncMock(side_effect=Exception("TTL Err"))):
			await pulse._maintenance_ritual()

	# global maint error (108)
	# Using a side effect on attribute access to force exception outside inner try
	with patch("red_pill.heartbeat.cfg") as mock_cfg:
		type(mock_cfg).METABOLISM_STRATEGY = PropertyMock(side_effect=Exception("Hard Fail"))
		await pulse._maintenance_ritual()

	# dream individual error (123)
	with patch("asyncio.to_thread", AsyncMock(side_effect=Exception("Dream Individual Fail"))):
		await pulse._dream_ritual()

	# dream global error (127)
	with patch("red_pill.heartbeat.logger.info", side_effect=Exception("Dream Hard Fail")):
		await pulse._dream_ritual()


def test_event_loop_coverage(pulse):
	mock_loop = MagicMock()
	with patch("asyncio.new_event_loop", return_value=mock_loop), patch("asyncio.set_event_loop"):
		pulse._run_event_loop()
		assert mock_loop.run_forever.called
