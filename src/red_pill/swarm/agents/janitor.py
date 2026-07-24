"""JanitorMinion — orquestador agnóstico de limpieza nocturna.

Mismo patrón que SovereignDaemon/DaemonPlugin, SleepPhase y SentinelPlugin:
el minion no sabe QUÉ se limpia — descubre los JanitorPlugins del paquete
`janitor_plugins/`, ejecuta los habilitados y agrega sus resultados.
Añadir una limpieza nueva = un archivo nuevo en janitor_plugins/, sin tocar
este orquestador.
"""

import importlib
import logging
import pkgutil
from typing import Any, Dict, List

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin
from red_pill.swarm.base import Minion

logger = logging.getLogger(__name__)


def discover_plugins() -> List[JanitorPlugin]:
	"""Auto-descubre las subclases de JanitorPlugin del paquete janitor_plugins."""
	import red_pill.swarm.agents.janitor_plugins as plugins_pkg

	plugins: List[JanitorPlugin] = []
	for _importer, mod_name, _ispkg in pkgutil.iter_modules(plugins_pkg.__path__):
		if mod_name.startswith("_") or mod_name == "base":
			continue
		try:
			module = importlib.import_module(f"red_pill.swarm.agents.janitor_plugins.{mod_name}")
			for attr_name in dir(module):
				attr = getattr(module, attr_name)
				if isinstance(attr, type) and issubclass(attr, JanitorPlugin) and attr is not JanitorPlugin:
					plugins.append(attr())
		except Exception as e:
			logger.error(f"[Janitor] Failed to load plugin module '{mod_name}': {e}")
	# Orden determinista: mismo barrido cada noche, logs comparables.
	plugins.sort(key=lambda p: p.name)
	return plugins


class JanitorMinion(Minion):
	"""
	Specialized Minion for system maintenance and garbage collection.
	Agnostic orchestrator: keeps the ecosystem clean by running JanitorPlugins.
	"""

	name: str = "Janitor"
	specialization: str = "System Maintenance and Garbage Collection"

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""Ejecuta un ciclo de limpieza recorriendo los plugins habilitados."""
		self.log("--- [Janitor] Initializing Cleaning Cycle (plugin sweep) ---")

		config_dict: Dict[str, Any] = dict(kwargs.get("config", {}))
		# Retrocompat: run_janitor_sweep pasa days_to_keep como kwarg global — se
		# inyecta como default de los plugins de retención corta sin pisar una
		# config explícita del operador.
		if "days_to_keep" in kwargs:
			plugins_cfg = config_dict.setdefault("plugins", {})
			for plugin_name in ("events_db_purge", "scratch_purge", "log_rotation"):
				plugins_cfg.setdefault(plugin_name, {}).setdefault("days_to_keep", kwargs["days_to_keep"])

		results: Dict[str, Any] = {"status": "success", "plugins_run": 0, "plugins_failed": 0}
		for plugin in discover_plugins():
			if not plugin.is_enabled(config_dict):
				self.log(f"[Janitor] Plugin '{plugin.name}' disabled by config. Skipping.")
				continue
			try:
				plugin_results = await plugin.execute(self, config_dict, **kwargs)
				results.update(plugin_results or {})
				results["plugins_run"] += 1
			except Exception as e:
				logger.error(f"[Janitor] Plugin '{plugin.name}' failed: {e}")
				results["plugins_failed"] += 1

		if results["plugins_failed"]:
			results["status"] = "partial"
		return results
