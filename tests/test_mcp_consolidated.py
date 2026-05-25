from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import red_pill.mcp_server  # noqa: F401
from red_pill.registry import registry

pytestmark = pytest.mark.asyncio


async def test_consolidated_list_tools():
	tools = registry.get_tools()
	tool_names = [t.name for t in tools]
	assert "bunker_memory_api" in tool_names
	assert "metabolism_health_api" in tool_names
	assert "swarm_orchestrator_api" in tool_names

	# Verify that the schema is flat (action + payload)
	bunker_tool = next(t for t in tools if t.name == "bunker_memory_api")
	schema = bunker_tool.inputSchema
	assert schema["type"] == "object"
	assert "action" in schema["properties"]
	assert "payload" in schema["properties"]
	assert "search_memory_research" in schema["properties"]["action"]["enum"]


async def test_consolidated_execute_success():
	# Test direct call to parent tool using unified signature
	swarm_result = MagicMock()
	swarm_result.status = "success"
	swarm_result.result = {"synthesis": "Test output"}

	mock_gru = MagicMock()
	mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])

	with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
		with patch("red_pill.mcp_server.OracleMinion"):
			result = await registry.execute(
				"bunker_memory_api",
				{"action": "search_memory_research", "payload": {"query": "test query"}}
			)
			assert len(result) == 1
			assert "started" in result[0].text or "Oracle" in result[0].text


async def test_consolidated_execute_compatibility_shim():
	# Test calling the legacy name directly on the registry (transparent redirection)
	swarm_result = MagicMock()
	swarm_result.status = "success"
	swarm_result.result = {"synthesis": "Test output"}

	mock_gru = MagicMock()
	mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])

	with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
		with patch("red_pill.mcp_server.OracleMinion"):
			# Calling using legacy name: search_memory_research
			result = await registry.execute(
				"search_memory_research",
				{"query": "test query"}
			)
			assert len(result) == 1
			assert "started" in result[0].text


async def test_consolidated_execute_invalid_action():
	with pytest.raises(ValueError, match="Unknown action"):
		await registry.execute("bunker_memory_api", {"action": "invalid_action_name"})
