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
	# Scored recall (RFC-002 §4.7.1) must be exposed as a first-class action.
	assert "recall" in schema["properties"]["action"]["enum"]


async def test_consolidated_execute_success():
	# Test direct call to parent tool using unified signature
	swarm_result = MagicMock()
	swarm_result.status = "success"
	swarm_result.result = {"synthesis": "Test output"}

	mock_gru = MagicMock()
	mock_gru.deploy_swarm = AsyncMock(return_value=[swarm_result])

	with patch("red_pill.mcp_server.GruOrchestrator", return_value=mock_gru):
		with patch("red_pill.mcp_server.OracleMinion"):
			result = await registry.execute("bunker_memory_api", {"action": "search_memory_research", "payload": {"query": "test query"}})
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
			result = await registry.execute("search_memory_research", {"query": "test query"})
			assert len(result) == 1
			assert "started" in result[0].text


async def test_consolidated_execute_invalid_action():
	with pytest.raises(ValueError, match="Unknown action"):
		await registry.execute("bunker_memory_api", {"action": "invalid_action_name"})


async def test_recall_action_dispatches():
	# Hermetic: MemoryManager is mocked, so no live Qdrant is needed.
	hit = MagicMock()
	hit.payload = {"content": "engrama de prueba", "reinforcement_score": 0.87, "color": "gray", "intensity": 1.0}
	mock_manager = MagicMock()
	mock_manager.search_and_reinforce.return_value = [hit]

	with patch("red_pill.memory.MemoryManager", return_value=mock_manager):
		result = await registry.execute(
			"bunker_memory_api",
			{"action": "recall", "payload": {"query": "prueba", "collection": "work", "limit": 2}},
		)

	assert len(result) == 1
	text = result[0].text
	assert "WORK_MEMORIES" in text  # alias 'work' resolved to the collection
	assert "engrama de prueba" in text
	assert "Score: 0.87" in text
	mock_manager.search_and_reinforce.assert_called_once()
	_, kwargs = mock_manager.search_and_reinforce.call_args
	assert kwargs.get("hybrid") is True  # hot-path policy = scored hybrid recall (RFC-002 §4.7.1)
