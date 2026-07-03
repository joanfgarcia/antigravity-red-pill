from abc import ABC, abstractmethod
from typing import Any, Dict


class JanitorPlugin(ABC):

	@property
	@abstractmethod
	def name(self) -> str:
		"""Nombre legible del plugin de limpieza (ej: 'events_db_purge')"""
		pass

	def is_enabled(self, config_dict: dict) -> bool:
		"""
		Determina si el plugin está activo según la configuración YAML.
		El comportamiento por defecto busca una clave coincidente con el nombre del plugin.
		"""
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		if isinstance(plugin_cfg, dict):
			return bool(plugin_cfg.get("enabled", True))
		return bool(plugin_cfg)

	@abstractmethod
	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		"""
		Ejecuta la tarea de limpieza del Janitor.
		Devuelve un diccionario con los resultados de la limpieza.
		"""
		pass
