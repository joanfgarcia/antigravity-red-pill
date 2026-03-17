import shutil
import tempfile
from pathlib import Path

import pytest

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
		(temp_workspace / "specs").mkdir()
		assert adapter.detect_flow() == "simple"
		assert adapter.is_specs_aware()
		shutil.rmtree(temp_workspace / "specs")
		(temp_workspace / ".specsmd/fire/resources").mkdir(parents=True)
		(temp_workspace / ".specsmd/fire/resources/state.yaml").touch()
		assert adapter.detect_flow() == "fire"
		shutil.rmtree(temp_workspace / ".specsmd")
		(temp_workspace / "aidlc-docs").mkdir()
		assert adapter.detect_flow() == "aidlc"

	def test_specs_adapter_data_retrieval(self, temp_workspace):
		adapter = SpecsAdapter(str(temp_workspace))
		(temp_workspace / ".specsmd/fire/resources").mkdir(parents=True)
		state_file = temp_workspace / ".specsmd/fire/resources/state.yaml"
		state_file.write_text("intents: [{label: 'Test Intent'}]")
		assert adapter.get_fire_intents() == [{"label": "Test Intent"}]
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
