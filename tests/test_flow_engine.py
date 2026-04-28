import pytest

from red_pill.config import FLOW_REGISTRY_PATH
from red_pill.swarm.flow_engine import FlowEngine
from red_pill.swarm.orchestrator import GruOrchestrator


@pytest.fixture
def flow_engine():
	return FlowEngine(FLOW_REGISTRY_PATH)


def test_load_global_flows(flow_engine):
	flows = flow_engine.load_flows()
	assert "pre-pr" in flows
	assert "surgical-fix" in flows


def test_local_override_and_lock(tmp_path, flow_engine):
	# Setup local .agent directory
	agent_dir = tmp_path / ".agent"
	agent_dir.mkdir()

	# Create a local override for a non-locked flow
	flows_yaml = agent_dir / "flows.yaml"
	flows_yaml.write_text("flows:\n  deep-research:\n    name: 'Custom Research'\n    locked: false\n")

	# Load flows pointing to tmp_path as CWD
	flows = flow_engine.load_flows(cwd=str(tmp_path))
	assert flows["deep-research"]["name"] == "Custom Research"


def test_lock_enforcement(tmp_path, flow_engine):
	# Setup a "Community" locked flow manually for test
	comm_file = tmp_path / "community_flows.yaml"
	comm_file.write_text("flows:\n  compliance-audit:\n    name: 'Enterprise Audit'\n    locked: true\n")

	engine = FlowEngine(FLOW_REGISTRY_PATH, community_registry_path=str(comm_file))

	# Attempt local override
	agent_dir = tmp_path / ".agent"
	agent_dir.mkdir()
	flows_yaml = agent_dir / "flows.yaml"
	flows_yaml.write_text("flows:\n  compliance-audit:\n    name: 'Hacked Audit'\n")

	flows = engine.load_flows(cwd=str(tmp_path))
	# Should resist override because it's locked in community layer
	assert flows["compliance-audit"]["name"] == "Enterprise Audit"


@pytest.mark.asyncio
async def test_orchestrator_run_flow_basic():
	gru = GruOrchestrator()
	# Test that it detects flows
	flows = gru.flow_engine.load_flows()
	assert "pre-pr" in flows

	# We don't run the full flow in unit tests to avoid GPU/CLI side effects
	# but we verify the method exists and handles invalid IDs
	with pytest.raises(ValueError):
		await gru.run_autonomous_flow("invalid-flow-id")
