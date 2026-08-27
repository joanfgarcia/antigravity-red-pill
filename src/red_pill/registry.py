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
		self._actions: Dict[str, Dict[str, Dict[str, Any]]] = {}
		self._current_auth_level = int(os.getenv("RED_PILL_AUTH_LEVEL", "1"))

	def register(self, name: str, description: str, schema: Dict[str, Any], auth_level: int = 1):
		"""Decorator to register a legacy tool handler with authorization level."""

		def decorator(func: Callable):
			self._tools[name] = types.Tool(name=name, description=description, inputSchema=schema)
			self._handlers[name] = func
			self._auth_levels[name] = auth_level
			return func

		return decorator

	def register_action(
		self, parent: str, action: str, description: str, schema: Dict[str, Any], legacy_alias: Optional[str] = None, auth_level: int = 1
	):
		"""Decorator to register a sub-action under a consolidated parent tool."""

		def decorator(func: Callable):
			if parent not in self._actions:
				self._actions[parent] = {}
			self._actions[parent][action] = {
				"description": description,
				"schema": schema,
				"handler": func,
				"legacy_alias": legacy_alias,
				"auth_level": auth_level,
			}
			return func

		return decorator

	def get_tools(self) -> List[types.Tool]:
		"""Returns all registered tool definitions (including dynamically generated parents)."""
		tools = list(self._tools.values())

		# Generate consolidated schemas
		for parent, actions in self._actions.items():
			parent_desc = f"Consolidated API for {parent}.\n\nActions:\n"
			action_enums = []
			for act_name, act_info in actions.items():
				parent_desc += f"- '{act_name}': {act_info['description']}\n"
				action_enums.append(act_name)

			parent_schema = {
				"type": "object",
				"properties": {
					"action": {"type": "string", "enum": action_enums, "description": f"The specific action to execute under {parent}."},
					"payload": {"type": "object", "description": "Serialized parameters matching the specified action."},
				},
				"required": ["action", "payload"],
			}

			tools.append(types.Tool(name=parent, description=parent_desc, inputSchema=parent_schema))
		return tools

	async def execute(
		self, name: str, arguments: Optional[Dict[str, Any]]
	) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
		"""Executes a registered tool handler with auditing and permission checks."""
		# 1. Compatibility Shim: check if calling a legacy alias or a sub-action name directly
		if name not in self._handlers and name not in self._actions:
			for parent_name, actions in self._actions.items():
				for act_name, act_info in actions.items():
					if name == act_name or name == act_info.get("legacy_alias"):
						# Forward to the parent tool as the designated action
						return await self.execute(parent_name, {"action": act_name, "payload": arguments or {}})
			raise ValueError(f"Unknown tool: {name}")

		# 2. Consolidated API execution
		if name in self._actions:
			args = arguments or {}
			action = args.get("action")
			payload = args.get("payload")

			if not action:
				# Attempt to infer action from payload keys
				for act_name, act_info in self._actions[name].items():
					req_keys = act_info["schema"].get("required", [])
					if req_keys and all(k in args for k in req_keys):
						action = act_name
						payload = args
						break
				if not action:
					raise ValueError(f"Consolidated tool '{name}' called without action and unable to infer target.")
			else:
				if payload is None:
					payload = {}

			if action not in self._actions[name]:
				raise ValueError(f"Unknown action '{action}' under parent tool '{name}'")

			action_info = self._actions[name][action]
			handler = action_info["handler"]
			required_level = action_info["auth_level"]

			if self._current_auth_level < required_level:
				logger.warning(f"Access Denied: Action '{action}' requires auth_level {required_level}")
				return [types.TextContent(type="text", text=f"Error: Access Denied. Auth level {required_level} required.")]

			try:
				from red_pill.core.providers import ProviderRegistry

				audit_provider = ProviderRegistry.get_telemetry_provider()
				audit_provider.log_event("ACTION_START", {"tool": name, "action": action, "args": payload})
			except Exception as e:
				logger.error(f"Sentinel Audit Failed (Degraded Mode): {e}")

			try:
				# RFC-002 §4.6: el ACTION_START era efímero; las queries de recall se persisten
				from red_pill.core.query_log import record_query

				record_query(action, payload)
			except Exception as e:
				logger.debug(f"Query log persistence failed (non-fatal): {e}")

			try:
				result = await handler(payload)
				if not isinstance(result, list):
					result = [types.TextContent(type="text", text=str(result))]
				try:
					audit_provider.log_event("ACTION_FINISH", {"tool": name, "action": action, "status": "success"})
				except Exception:
					pass
				return result
			except Exception as e:
				logger.error(f"Action {action} on tool {name} execution failed: {e}")
				try:
					audit_provider.log_event("ACTION_FINISH", {"tool": name, "action": action, "status": "failed", "error": str(e)})
				except Exception:
					pass
				return [types.TextContent(type="text", text=f"Error: {str(e)}")]

		# 3. Legacy Tool execution
		if name not in self._handlers:
			raise ValueError(f"Unknown tool: {name}")

		required_level = self._auth_levels.get(name, 1)
		if self._current_auth_level < required_level:
			logger.warning(f"Access Denied: Tool '{name}' requires auth_level {required_level}")
			return [types.TextContent(type="text", text=f"Error: Access Denied. Auth level {required_level} required.")]

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
			try:
				audit_provider.log_event("TOOL_FINISH", {"tool": name, "status": "success"})
			except Exception:
				pass
			return result
		except Exception as e:
			logger.error(f"Tool {name} execution failed: {e}")
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
