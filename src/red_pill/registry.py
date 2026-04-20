import logging
import os
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
		self._auth_levels: Dict[str, int] = {}
		self._current_auth_level = int(os.getenv("RED_PILL_AUTH_LEVEL", "1"))

	def register(self, name: str, description: str, schema: Dict[str, Any], auth_level: int = 1):
		"""Decorator to register a tool handler with authorization level."""

		def decorator(func: Callable):
			self._tools[name] = types.Tool(name=name, description=description, inputSchema=schema)
			self._handlers[name] = func
			self._auth_levels[name] = auth_level
			return func

		return decorator

	def get_tools(self) -> List[types.Tool]:
		"""Returns all registered tool definitions."""
		return list(self._tools.values())

	async def execute(
		self, name: str, arguments: Optional[Dict[str, Any]]
	) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
		"""Executes a registered tool handler with auditing and permission checks."""
		if name not in self._handlers:
			raise ValueError(f"Unknown tool: {name}")

		# 1. Permission Check (Hardening v6.8)
		required_level = self._auth_levels.get(name, 1)
		if self._current_auth_level < required_level:
			logger.warning(f"Access Denied: Tool '{name}' requires auth_level {required_level}")
			return [types.TextContent(type="text", text=f"Error: Access Denied. Auth level {required_level} required.")]

		# 2. Audit Start (Sentinel)
		try:
			from red_pill.core.providers import ProviderRegistry
			audit_provider = ProviderRegistry.get_telemetry_provider()
			audit_provider.log_event("TOOL_START", {"tool": name, "args": arguments})
		except Exception as e:
			logger.error(f"Sentinel Audit Failed (Degraded Mode): {e}")

		handler = self._handlers[name]
		try:
			result = await handler(arguments or {})
			if not isinstance(result, list):
				result = [types.TextContent(type="text", text=str(result))]

			# 3. Audit End (Sentinel)
			try:
				audit_provider.log_event("TOOL_FINISH", {"tool": name, "status": "success"})
			except Exception:
				pass

			return result
		except Exception as e:
			logger.error(f"Tool {name} execution failed: {e}")

			# Audit Error (Sentinel)
			try:
				audit_provider.log_event("TOOL_FINISH", {"tool": name, "status": "failed", "error": str(e)})
			except Exception:
				pass

			return [types.TextContent(type="text", text=f"Error: {str(e)}")]


# Global Registry instance
registry = ToolRegistry()

# Enterprise Mode: Provider Initialization
from red_pill.core.providers import ProviderRegistry  # noqa: E402
from red_pill.telemetry import sentinel  # noqa: E402

ProviderRegistry.register_telemetry_provider(sentinel)
