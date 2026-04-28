"""Tests for swarm/orchestrator.py — targeting lines 24, 44-45."""

from unittest.mock import MagicMock, patch

import pytest


class TestGruOrchestrator:
	def test_is_local_ready_no_dir(self, tmp_path):
		"""Line 24: model dir doesn't exist → returns False."""
		from red_pill.swarm.orchestrator import GruOrchestrator

		gru = GruOrchestrator()
		with patch("os.path.exists", return_value=False):
			result = gru.is_local_ready()
		assert result is False

	def test_is_local_ready_with_gguf(self, tmp_path):
		"""Line 25: model dir exists with .gguf → returns True."""
		from red_pill.swarm.orchestrator import GruOrchestrator

		model_dir = tmp_path / "models"
		model_dir.mkdir()
		(model_dir / "model.gguf").write_bytes(b"fake")
		with patch("os.getenv", return_value=str(tmp_path)):
			gru = GruOrchestrator()
			result = gru.is_local_ready()
		assert result is True

	@pytest.mark.asyncio
	async def test_deploy_swarm_success(self):
		"""Lines 29-37: minions deployed, notify_user called."""
		from red_pill.swarm.orchestrator import GruOrchestrator

		gru = GruOrchestrator()
		mock_minion = MagicMock()
		mock_minion.id = "test-id"

		async def fake_execute(task, **kwargs):
			return {"status": "ok"}

		mock_minion.execute = fake_execute
		with patch("red_pill.swarm.orchestrator.notify_user") as mock_notify:
			results = await gru.deploy_swarm("health_check", [mock_minion])
		assert mock_notify.called
		assert len(results) == 1

	@pytest.mark.asyncio
	async def test_run_minion_success(self):
		"""Line 42-43: execute succeeds → SwarmResult with status='success'."""
		from red_pill.swarm.orchestrator import GruOrchestrator

		gru = GruOrchestrator()
		mock_minion = MagicMock()
		mock_minion.id = "m-001"
		mock_minion.execute = MagicMock(return_value={"data": 42})

		async def fake_execute(task, **kwargs):
			return {"data": 42}

		mock_minion.execute = fake_execute
		result = await gru._run_minion(mock_minion, "test_task")
		assert result.status == "success"
		assert result.minion_id == "m-001"

	@pytest.mark.asyncio
	async def test_run_minion_exception(self):
		"""Lines 44-45: execute raises → SwarmResult with status='failed'."""
		from red_pill.swarm.orchestrator import GruOrchestrator

		gru = GruOrchestrator()
		mock_minion = MagicMock()
		mock_minion.id = "m-002"

		async def failing_execute(task, **kwargs):
			raise RuntimeError("minion crashed")

		mock_minion.execute = failing_execute
		result = await gru._run_minion(mock_minion, "test_task")
		assert result.status == "failed"
		assert "crashed" in result.error  # type: ignore
