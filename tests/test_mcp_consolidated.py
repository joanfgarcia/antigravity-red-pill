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

	with (
		patch("red_pill.memory.MemoryManager", return_value=mock_manager),
		patch("red_pill.recall_demand.record_recall", return_value=False),
	):
		result = await registry.execute(
			"bunker_memory_api",
			{"action": "recall", "payload": {"query": "prueba", "collection": "work", "limit": 2}},
		)

	assert len(result) == 1
	text = result[0].text
	assert "WORK_MEMORIES" in text  # alias 'work' resolved to the collection
	assert "engrama de prueba" in text
	# MEM-012 F1: la línea separa similitud (relevancia) de utilidad (score bayesiano).
	assert "util 0.87" in text
	assert "sim " in text
	assert "confianza ALTA" in text
	mock_manager.search_and_reinforce.assert_called_once()
	_, kwargs = mock_manager.search_and_reinforce.call_args
	assert kwargs.get("hybrid") is True  # hot-path policy = scored hybrid recall (RFC-002 §4.7.1)


async def test_recall_marca_no_recall_y_solo_materializa_la_banda_si_se_pide():
	"""MEM-012 F2: D-AB-03 (no oculta) + D-AB-04 (la puerta es explícita)."""
	low = MagicMock()
	low.id = "low-1"
	low.score = 0.21
	low.payload = {"content": "recuerdo flojo", "reinforcement_score": 1.2, "color": "gray", "intensity": 1.0}
	mock_manager = MagicMock()
	mock_manager.search_and_reinforce.return_value = [low]

	with (
		patch("red_pill.memory.MemoryManager", return_value=mock_manager),
		patch("red_pill.recall_demand.record_recall", return_value=False),
	):
		abstained = await registry.execute(
			"bunker_memory_api",
			{"action": "recall", "payload": {"query": "receta de paella", "collection": "work", "limit": 2}},
		)
		inspected = await registry.execute(
			"bunker_memory_api",
			{"action": "recall", "payload": {"query": "receta de paella", "collection": "work", "limit": 2, "include_below_floor": True}},
		)

	text = abstained[0].text
	assert "no_recall" in text
	assert "INSUFICIENTE" in text
	assert "candidato(s) por debajo" in text
	assert "search_memento(query=" in text, "F4: la oferta de Memento es accionable"
	assert "no se ejecutan solas" in text
	assert "recuerdo flojo" not in text, "por defecto la banda no se materializa"

	text_below = inspected[0].text
	assert "recuerdo flojo" in text_below
	assert "insuficiente" in text_below, "la banda baja viaja marcada (inspección)"


async def test_recall_de_confianza_baja_ofrece_memento_sin_ejecutarlo():
	"""F4: también en `baja` la oferta es accionable, y el hit sigue saliendo."""
	hit = MagicMock()
	hit.id = "rocky-1"
	hit.score = 0.3971
	hit.payload = {"content": "la escena de Rocky", "reinforcement_score": 3.0, "color": "gray", "intensity": 1.0}
	mock_manager = MagicMock()
	mock_manager.search_and_reinforce.return_value = [hit]

	with (
		patch("red_pill.memory.MemoryManager", return_value=mock_manager),
		patch("red_pill.recall_demand.record_recall", return_value=False),
	):
		result = await registry.execute(
			"bunker_memory_api",
			{"action": "recall", "payload": {"query": "Rocky la cobaya rescatada", "collection": "social", "limit": 2}},
		)

	text = result[0].text
	assert "confianza BAJA" in text
	assert "la escena de Rocky" in text
	assert "search_memento(query=" in text
