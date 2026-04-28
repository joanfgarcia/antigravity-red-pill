"""Tests for swarm/agents/keymaker.py — targeting lines 25-77."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def keymaker():
	from red_pill.swarm.agents.keymaker import KeymakerMinion

	return KeymakerMinion()


@pytest.mark.asyncio
async def test_qdrant_down_degraded(keymaker):
	"""Lines 29-45, 74-75: qdrant unreachable → status='degraded'."""
	with patch("requests.get", side_effect=Exception("timeout")):
		with patch("psutil.disk_usage", return_value=MagicMock(percent=50.0, free=10 * 1024**3)):
			with patch("red_pill.swarm.agents.keymaker.HardwareSentinel.get_stats", return_value={}):
				result = await keymaker.execute("health")
	assert result["status"] == "degraded"
	assert result["qdrant_online"] is False


@pytest.mark.asyncio
async def test_qdrant_up_optimal(keymaker):
	"""Lines 31-43: qdrant online → status='optimal'."""
	mock_resp = MagicMock(status_code=200)
	with patch("requests.get", return_value=mock_resp):
		with patch("psutil.disk_usage", return_value=MagicMock(percent=30.0, free=50 * 1024**3)):
			with patch("red_pill.swarm.agents.keymaker.HardwareSentinel.get_stats", return_value={}):
				result = await keymaker.execute("health")
	assert result["status"] == "optimal"
	assert result["qdrant_online"] is True


@pytest.mark.asyncio
async def test_npu_active_status_reported(keymaker):
	"""Lines 56-58: NPU status=Ready → npu_status='Active'."""
	with patch("requests.get", side_effect=Exception("no qdrant")):
		with patch("psutil.disk_usage", return_value=MagicMock(percent=20.0, free=100 * 1024**3)):
			with patch("red_pill.swarm.agents.keymaker.HardwareSentinel.get_stats", return_value={"npu": {"status": "Ready", "name": "Mali-G710"}}):
				result = await keymaker.execute("health")
	assert result["npu_status"] == "Active"
	assert any(("NPU" in c["component"] for c in result["checks"]))


@pytest.mark.asyncio
async def test_heal_task_with_active_npu_runs_sanitize(keymaker):
	"""Lines 63-72: task='heal' + npu active → MemoryManager.sanitize called."""
	import sys

	mock_resp = MagicMock(status_code=200)
	mock_mm = MagicMock()
	mock_mm_class = MagicMock(return_value=mock_mm)
	import types

	fake_memory = types.ModuleType("red_pill.memory")
	fake_memory.MemoryManager = mock_mm_class  # type: ignore
	original = sys.modules.get("red_pill.memory")
	sys.modules["red_pill.memory"] = fake_memory
	try:
		with patch("requests.get", return_value=mock_resp):
			with patch("psutil.disk_usage", return_value=MagicMock(percent=20.0, free=100 * 1024**3)):
				with patch("red_pill.swarm.agents.keymaker.HardwareSentinel.get_stats", return_value={"npu": {"status": "Ready", "name": "NPU"}}):
					result = await keymaker.execute("heal")
	finally:
		if original is not None:
			sys.modules["red_pill.memory"] = original
		elif "red_pill.memory" in sys.modules:
			del sys.modules["red_pill.memory"]
	assert mock_mm.sanitize.called
	assert any(("Healing" in c["component"] for c in result["checks"]))


@pytest.mark.asyncio
async def test_npu_not_ready_offline_reported(keymaker):
	"""Lines 59-60: NPU not ready → npu_status='Undetected', OFFLINE check."""
	with patch("requests.get", side_effect=Exception("no qdrant")):
		with patch("psutil.disk_usage", return_value=MagicMock(percent=40.0, free=20 * 1024**3)):
			with patch("red_pill.swarm.agents.keymaker.HardwareSentinel.get_stats", return_value={"npu": {"status": "Unavailable"}}):
				result = await keymaker.execute("health")
	assert result["npu_status"] == "Undetected"
	assert any(("OFFLINE" in c.get("status", "") for c in result["checks"]))
