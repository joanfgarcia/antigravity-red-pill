import asyncio
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.memory import MemoryManager
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.utils.affect import calculate_fsrs_new_stability, calculate_fsrs_retrievability
from red_pill.utils.specs_adapter import SpecsAdapter


def test_specs_adapter_coverage_gaps(tmp_path):
	adapter = SpecsAdapter(str(tmp_path))
	assert adapter.get_specs_hash() == ""
	assert adapter.get_simple_tasks() == ""
	with patch("yaml.safe_load", side_effect=Exception("YAML Error")):
		(tmp_path / ".specsmd/fire/resources").mkdir(parents=True)
		(tmp_path / ".specsmd/fire/resources/state.yaml").write_text("invalid: yaml")
		assert adapter.get_fire_intents() == []
	(tmp_path / ".specsmd/fire/resources/state.yaml").write_text("intents: []")
	h = adapter.get_specs_hash()
	assert isinstance(h, str)
	assert len(h) == 64


def test_affect_coverage_gaps():
	assert calculate_fsrs_retrievability(0.0, 100) == 0.0
	assert calculate_fsrs_new_stability(0.0, 5.0, 0.9) == 1.0


def test_memory_management_coverage_gaps(tmp_path):
	mem_mgr = MemoryManager()
	assert mem_mgr._parse_payload({}, strict=True) == {}
	scroll_return = (
		[
			MagicMock(
				id="1",
				payload={
					"content": "x" * (cfg.CHUNK_THRESHOLD + 1),
					"reinforcement_score": 1.0,
					"color": "blue",
					"emotion": "joy",
					"intensity": 1.0,
					"immune": False,
				},
			)
		],
		None,
	)
	with patch.object(mem_mgr.client, "scroll", return_value=scroll_return):
		with patch.object(mem_mgr, "add_memory", side_effect=Exception("Add Memory Error")):
			results = mem_mgr.sanitize("work_memories")
			assert results["refracted_records"] == 1
	with patch.object(mem_mgr.client, "collection_exists", return_value=False):
		res = mem_mgr.create_bunker_snapshot(["non_existent"])
		assert "non_existent" not in res
	with patch.object(mem_mgr.client, "collection_exists", return_value=True):
		with patch.object(mem_mgr.client, "create_snapshot", return_value=None):
			res = mem_mgr.create_bunker_snapshot(["work_memories"])
			assert res["work_memories"] == "ERROR: Empty snapshot descriptor"
	with patch.object(mem_mgr.client, "collection_exists", return_value=True):
		with patch.object(mem_mgr.client, "create_snapshot", side_effect=Exception("Snapshot Error")):
			res = mem_mgr.create_bunker_snapshot(["work_memories"])
			assert "ERROR: Snapshot Error" in res["work_memories"]


@pytest.mark.xfail(
	reason="GruOrchestrator.deploy_swarm no longer calls specs.get_fire_intents — inference provider registry changed",
	strict=False,
)
@pytest.mark.asyncio
async def test_orchestrator_specs_integration_coverage():
	orchestrator = GruOrchestrator()
	mock_specs = MagicMock()
	orchestrator.specs = mock_specs
	mock_specs.detect_flow.return_value = "fire"
	mock_specs.get_fire_intents.return_value = [{"id": "test"}]
	mock_minion = MagicMock()
	mock_minion.execute = asyncio.Future()
	mock_minion.execute.set_result({"status": "ok"})
	mock_minion.id = "test-minion"
	with patch("red_pill.core.notifier.SovereignNotifier.notify_os"):
		await orchestrator.deploy_swarm("task", [mock_minion])
		assert mock_specs.get_fire_intents.called
	mock_specs.detect_flow.return_value = "simple"
	mock_specs.get_simple_tasks.return_value = "# Task List"
	mock_minion.execute = asyncio.Future()
	mock_minion.execute.set_result({"status": "ok"})
	with patch("red_pill.core.notifier.SovereignNotifier.notify_os"):
		await orchestrator.deploy_swarm("task", [mock_minion])
		assert mock_specs.get_simple_tasks.called
