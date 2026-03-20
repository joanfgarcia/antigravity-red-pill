import asyncio
import importlib
import logging
import pkgutil
from pathlib import Path

from red_pill.interceptors.base import BaseInterceptorPlugin

logger = logging.getLogger(__name__)

# Cache loaded plugins to avoid I/O on every prompt
_PLUGINS: list[BaseInterceptorPlugin] = []


def load_plugins():
	global _PLUGINS
	if _PLUGINS:
		return

	package_dir = Path(__file__).resolve().parent
	for _, module_name, _ in pkgutil.iter_modules([str(package_dir)]):
		if module_name == "base":
			continue

		try:
			module = importlib.import_module(f"red_pill.interceptors.{module_name}")
			# Find classes inheriting from BaseInterceptorPlugin
			for attr_name in dir(module):
				attr = getattr(module, attr_name)
				if isinstance(attr, type) and issubclass(attr, BaseInterceptorPlugin) and attr is not BaseInterceptorPlugin:
					plugin_instance = attr()
					if plugin_instance.is_enabled:
						_PLUGINS.append(plugin_instance)
						logger.info(f"Loaded Interceptor Plugin: {plugin_instance.name}")
		except Exception as e:
			logger.error(f"Failed to load plugin {module_name}: {e}")

	# Sort plugins by name (01_..., 02_...) to guarantee execution order if needed
	_PLUGINS.sort(key=lambda p: p.__module__)


async def _run_plugin_safe(plugin: BaseInterceptorPlugin, prompt: str) -> str:
	try:
		return await asyncio.wait_for(plugin.execute(prompt), timeout=plugin.timeout)
	except asyncio.TimeoutError:
		logger.warning(f"Plugin {plugin.name} timed out after {plugin.timeout}s")
		return ""
	except Exception as e:
		logger.error(f"Plugin {plugin.name} crashed: {e}")
		return ""


async def execute_pipeline(user_prompt: str) -> str:
	"""
	Run all loaded plugins concurrently and merge their passive context outputs.
	If any plugin returns a <LOCAL_RESPONSE_READY> block, we short-circuit immediately.
	"""
	if not _PLUGINS:
		load_plugins()

	if not _PLUGINS:
		return user_prompt

	# Execute all plugins concurrently
	tasks = [_run_plugin_safe(p, user_prompt) for p in _PLUGINS]
	results = await asyncio.gather(*tasks)

	# Check for short-circuit
	for r in results:
		if r and "<LOCAL_RESPONSE_READY>" in r:
			return r  # Immediate short-circuit return

	# Merge all contexts safely
	valid_contexts = [r.strip() for r in results if r and r.strip()]

	if not valid_contexts:
		return user_prompt

	# Wrap passively
	merged = "\n".join(valid_contexts)
	wrapper = f"<bunker_context>\n{merged}\n</bunker_context>\n\n<user_request>\n{user_prompt}\n</user_request>"
	return wrapper
