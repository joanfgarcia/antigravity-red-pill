import logging
from typing import Any, Callable, Dict, List, Optional, Union

import mcp.types as types

logger = logging.getLogger(__name__)


class ToolRegistry:
	"""
	Centralized registry for Red Pill tools.
	Allows dynamic discovery of capabilities by both MCP and CLI.
	"""

	def __init__(self):
		self._tools: Dict[str, types.Tool] = {}
		self._handlers: Dict[str, Callable] = {}

	def register(self, name: str, description: str, schema: Dict[str, Any]):
		"""Decorator to register a tool handler."""

		def decorator(func: Callable):
			self._tools[name] = types.Tool(name=name, description=description, inputSchema=schema)
			self._handlers[name] = func
			return func

		return decorator

	def get_tools(self) -> List[types.Tool]:
		"""Returns all registered tool definitions."""
		return list(self._tools.values())

	async def execute(
		self, name: str, arguments: Optional[Dict[str, Any]]
	) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
		"""Executes a registered tool handler."""
		if name not in self._handlers:
			raise ValueError(f"Unknown tool: {name}")

		handler = self._handlers[name]
		try:
			result = await handler(arguments or {})
			if not isinstance(result, list):
				return [types.TextContent(type="text", text=str(result))]
			return result
		except Exception as e:
			logger.error(f"Tool {name} execution failed: {e}")
			return [types.TextContent(type="text", text=f"Error: {str(e)}")]


# Global Registry instance
registry = ToolRegistry()

# Enterprise Mode: Provider Initialization
from red_pill.core.providers import ProviderRegistry  # noqa: E402
from red_pill.telemetry import sentinel  # noqa: E402

ProviderRegistry.register_telemetry_provider(sentinel)
