import asyncio
import importlib
import logging
import pkgutil
from pathlib import Path

from red_pill.core.plugin_engine import PluginRegistry, PluginScope
from red_pill.events import SoulCreatedEvent, get_event_bus
from red_pill.interceptors.base import BaseInterceptorPlugin
from red_pill.plugins.cloud_sync.plugin import CloudSyncPlugin
from red_pill.plugins.gmail_watcher.plugin import GmailWatcherPlugin
from red_pill.plugins.trinity_homeostasis.plugin import HomeostasisPlugin
from red_pill.plugins.trinity_learning.plugin import BayesianLearningPlugin

logger = logging.getLogger(__name__)

# Cache loaded plugins to avoid I/O on every prompt
_PLUGINS: list[BaseInterceptorPlugin] = []

sovereign_registry = PluginRegistry()
_sovereign_loaded = False

async def _bridge_soul_event(event: SoulCreatedEvent):
	"""Bridge EventBus SoulCreatedEvent to PluginRegistry SYSTEM_EVENT hook."""
	payload = {
		"action": "soul_created",
		"zip_path": event.zip_path,
		"timestamp": event.timestamp
	}
	await sovereign_registry.emit_hook(PluginScope.SYSTEM_EVENT, payload)

async def _init_sovereign_plugins():
	global _sovereign_loaded
	if _sovereign_loaded:
		return


	p_homeo = HomeostasisPlugin(name="TrinityHomeostasis", version="1.0", directory=Path(__file__).parent.parent / "plugins" / "trinity_homeostasis")
	p_learn = BayesianLearningPlugin(name="TrinityLearning", version="1.0", directory=Path(__file__).parent.parent / "plugins" / "trinity_learning")
	p_cloud = CloudSyncPlugin(name="cloud_sync", version="1.0", directory=Path(__file__).parent.parent / "plugins" / "cloud_sync")
	p_gmail = GmailWatcherPlugin(name="gmail_watcher", version="1.0", directory=Path(__file__).parent.parent / "plugins" / "gmail_watcher")

	# Injection of the in-memory Qdrant mock for MVP to avoid breaking Real DB
	from qdrant_client import QdrantClient
	mock_db = QdrantClient(location=":memory:")
	p_learn.qdrant = mock_db  # type: ignore

	sovereign_registry.register(p_homeo)
	sovereign_registry.register(p_learn)
	sovereign_registry.register(p_cloud)
	sovereign_registry.register(p_gmail)

	# Bridge: Listen for local events and forward to plugins
	get_event_bus().subscribe(SoulCreatedEvent, lambda ev: asyncio.create_task(_bridge_soul_event(ev)))

	await sovereign_registry.activate_all()
	_sovereign_loaded = True




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

	if not _sovereign_loaded:
		await _init_sovereign_plugins()

	if not valid_contexts:
		merged = ""
	else:
		merged = "\n".join(valid_contexts)

	# --- TRINITY BRIDGE ---
	payload = {
		"user_prompt": user_prompt,
		"legacy_context": merged,
		"operator_friction": False,
	}

	try:
		mutated = await sovereign_registry.emit_hook(PluginScope.COGNITION, payload)
		merged = mutated.get("legacy_context", merged)
	except Exception as core_err:
		logger.error(f"Trinity Bünker Bridge failed: {core_err}")
	# -----------------------

	if not merged.strip():
		return user_prompt

	# Wrap passively
	wrapper = f"<bunker_context>\n{merged}\n</bunker_context>\n\n<user_request>\n{user_prompt}\n</user_request>"
	return wrapper
