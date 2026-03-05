import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from red_pill.memory import MemoryManager
from red_pill.swarm.base import Minion
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.utils.specs_adapter import SpecsAdapter


class TestSpecsIntegration:
	@pytest.fixture
	def temp_workspace(self):
		with tempfile.TemporaryDirectory() as tmpdir:
			yield Path(tmpdir)

	def test_specs_adapter_detection(self, temp_workspace):
		adapter = SpecsAdapter(str(temp_workspace))
		assert adapter.detect_flow() is None
		assert not adapter.is_specs_aware()

		# Simple
		(temp_workspace / "specs").mkdir()
		assert adapter.detect_flow() == "simple"
		assert adapter.is_specs_aware()
		shutil.rmtree(temp_workspace / "specs")

		# FIRE
		(temp_workspace / ".specs-fire").mkdir()
		(temp_workspace / ".specs-fire/state.yaml").touch()
		assert adapter.detect_flow() == "fire"
		shutil.rmtree(temp_workspace / ".specs-fire")

		# AI-DLC
		(temp_workspace / "aidlc-docs").mkdir()
		assert adapter.detect_flow() == "aidlc"

	def test_specs_adapter_data_retrieval(self, temp_workspace):
		adapter = SpecsAdapter(str(temp_workspace))

		# FIRE Intents
		(temp_workspace / ".specs-fire").mkdir()
		state_file = temp_workspace / ".specs-fire/state.yaml"
		state_file.write_text("intents: [{label: 'Test Intent'}]")
		assert adapter.get_fire_intents() == [{"label": "Test Intent"}]

		# Simple Tasks
		(temp_workspace / "specs").mkdir()
		tasks_file = temp_workspace / "specs/tasks.md"
		tasks_file.write_text("# Tasks\n- Task 1")
		assert "Task 1" in adapter.get_simple_tasks()

	def test_specs_hash_calculation(self, temp_workspace):
		adapter = SpecsAdapter(str(temp_workspace))
		(temp_workspace / "specs").mkdir()
		tasks_file = temp_workspace / "specs/tasks.md"
		tasks_file.write_text("V1")

		h1 = adapter.get_specs_hash()
		assert h1 != ""

		tasks_file.write_text("V2")
		h2 = adapter.get_specs_hash()
		assert h1 != h2

	def test_memory_manager_sync_metadata(self):
		with patch("red_pill.memory.QdrantClient") as mock_client:
			manager = MemoryManager()
			coll = "test_coll"
			h = "deadbeef"

			# Test set
			manager.set_sync_hash(coll, h)
			mock_client.return_value.upsert.assert_called()

			# Test get
			mock_client.return_value.retrieve.return_value = [MagicMock(payload={"sync_hash": h})]
			assert manager.get_sync_hash(coll) == h

	@pytest.mark.asyncio
	async def test_orchestrator_sync_shield(self, temp_workspace):
		# Setup workspace
		(temp_workspace / "specs").mkdir()
		tasks_file = temp_workspace / "specs/tasks.md"
		tasks_file.write_text("Task V1")

		with patch("red_pill.swarm.orchestrator.MemoryManager") as mock_mem_class:
			mock_mem = mock_mem_class.return_value
			# Initial state: mismatch
			mock_mem.get_sync_hash.return_value = "old_hash"

			with patch("os.getcwd", return_value=str(temp_workspace)):
				orch = GruOrchestrator()

				# Mock minion
				minion = MagicMock(spec=Minion)
				minion.execute.return_value = {"output": "ok"}
				minion.id = "test-minion"

				# Deploy
				await orch.deploy_swarm("Test Mission", [minion])

				# Verify Auto-Sync was triggered
				mock_mem.sync_specs.assert_called_with(str(temp_workspace))
				mock_mem.set_sync_hash.assert_called()

	def test_memory_manager_sync_specs_logic(self, temp_workspace):
		# Setup workspace as simple flow
		(temp_workspace / "specs").mkdir()
		(temp_workspace / "specs/artifact.md").write_text("Artifact Content")

		with patch("red_pill.memory.QdrantClient"):
			manager = MemoryManager()
			with patch.object(manager, "add_memory") as mock_add:
				manager.sync_specs(str(temp_workspace))
				mock_add.assert_called()
				args, kwargs = mock_add.call_args
				assert kwargs["collection"] == "specs_memories"
				assert "Artifact Content" in kwargs["text"]
