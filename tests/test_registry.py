import mcp.types as types
import pytest

from red_pill.registry import ToolRegistry


@pytest.fixture
def registry():
	return ToolRegistry()


def test_register_tool(registry):

	@registry.register(name="test_tool", description="Test description", schema={"type": "object"})
	async def test_handler(args):
		return [types.TextContent(type="text", text="ok")]

	tools = registry.get_tools()
	assert len(tools) == 1
	assert tools[0].name == "test_tool"
	assert tools[0].description == "Test description"


@pytest.mark.asyncio
async def test_execute_tool(registry):

	@registry.register(name="add", description="Add numbers", schema={"type": "object"})
	async def add_handler(args):
		return [types.TextContent(type="text", text=str(args["a"] + args["b"]))]

	result = await registry.execute("add", {"a": 1, "b": 2})
	assert result[0].text == "3"


@pytest.mark.asyncio
async def test_execute_unknown_tool(registry):
	with pytest.raises(ValueError, match="Unknown tool"):
		await registry.execute("non_existent", {})


@pytest.mark.asyncio
async def test_execute_tool_exception(registry):

	@registry.register(name="fail", description="Fail", schema={})
	async def fail_handler(args):
		raise RuntimeError("Boom")

	result = await registry.execute("fail", {})
	assert "Error: Boom" in result[0].text


@pytest.mark.asyncio
async def test_execute_tool_non_list_return(registry):

	@registry.register(name="raw", description="Raw return", schema={})
	async def raw_handler(args):
		return "just a string"

	result = await registry.execute("raw", {})
	assert result[0].text == "just a string"


@pytest.mark.asyncio
async def test_compatibility_shim_consolidated(registry):

	@registry.register_action(
		parent="system", action="info", description="System info", schema={"type": "object"}, legacy_alias="sysinfo", auth_level=1
	)
	async def info_handler(payload):
		return "system_ok"

	# Call directly via action name
	res1 = await registry.execute("info", {})
	assert res1[0].text == "system_ok"

	# Call via legacy alias
	res2 = await registry.execute("sysinfo", {})
	assert res2[0].text == "system_ok"


@pytest.mark.asyncio
async def test_execute_consolidated_action_inference(registry):

	@registry.register_action(parent="db", action="query", description="Query DB", schema={"type": "object", "required": ["sql"]})
	async def query_handler(payload):
		return f"executed: {payload.get('sql')}"

	# Call without action/payload, letting it infer action from "sql" key
	res = await registry.execute("db", {"sql": "SELECT 1"})
	assert res[0].text == "executed: SELECT 1"


@pytest.mark.asyncio
async def test_execute_consolidated_action_inference_fail(registry):

	@registry.register_action(parent="db", action="query", description="Query DB", schema={"type": "object", "required": ["sql"]})
	async def query_handler(payload):
		return "ok"

	# Call without action, but payload has no matching keys for inference
	with pytest.raises(ValueError, match="unable to infer target"):
		await registry.execute("db", {"not_sql": "SELECT 1"})


@pytest.mark.asyncio
async def test_execute_consolidated_unknown_action(registry):

	@registry.register_action(parent="db", action="query", description="Query DB", schema={"type": "object"})
	async def query_handler(payload):
		return "ok"

	with pytest.raises(ValueError, match="Unknown action 'delete'"):
		await registry.execute("db", {"action": "delete", "payload": {}})


@pytest.mark.asyncio
async def test_execute_consolidated_auth_denied(registry):
	registry._current_auth_level = 0

	@registry.register_action(parent="secure", action="wipe", description="Wipe system", schema={}, auth_level=2)
	async def wipe_handler(payload):
		return "wiped"

	res = await registry.execute("secure", {"action": "wipe", "payload": {}})
	assert "Error: Access Denied" in res[0].text


@pytest.mark.asyncio
async def test_execute_legacy_auth_denied(registry):
	registry._current_auth_level = 0

	@registry.register(name="wipe_legacy", description="Wipe", schema={}, auth_level=2)
	async def wipe_handler(payload):
		return "wiped"

	res = await registry.execute("wipe_legacy", {})
	assert "Error: Access Denied" in res[0].text


@pytest.mark.asyncio
async def test_execute_consolidated_non_list_return(registry):

	@registry.register_action(parent="calc", action="add", description="add", schema={})
	async def add_handler(payload):
		return "sum_result"

	res = await registry.execute("calc", {"action": "add", "payload": {}})
	assert res[0].text == "sum_result"


@pytest.mark.asyncio
async def test_execute_consolidated_exception(registry):

	@registry.register_action(parent="calc", action="fail", description="fail", schema={})
	async def fail_handler(payload):
		raise RuntimeError("calc_boom")

	res = await registry.execute("calc", {"action": "fail", "payload": {}})
	assert "Error: calc_boom" in res[0].text
