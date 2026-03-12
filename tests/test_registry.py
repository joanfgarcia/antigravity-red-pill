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
