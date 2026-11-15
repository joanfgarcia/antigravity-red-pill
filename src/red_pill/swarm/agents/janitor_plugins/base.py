import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

logger = logging.getLogger(__name__)


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


def bury_signal(name: str, *, muted: bool = False, memory_manager: Any = None) -> None:
	"""Entierra una señal cuando su causa desapareció (contrato de ciclo de vida).

	Un dolor que no se puede enterrar miente para siempre: medido el 2026-11-12,
	ocho de las nueve señales del Janitor seguían en el tablero (o en el buzón)
	mucho después de que el problema cesara. Se emite en el `if` y se entierra en
	el `else`, en el mismo pase.

	`muted=True` cierra el reporte del MinionInbox (`signal_<name>`), no un punto
	de Qdrant: las silenciadas no viven en el tablero y `evaporate_signals` no
	las alcanza.

	Nunca lanza: el Janitor no se cae por un entierro que no pudo ser.
	"""
	try:
		if muted:
			from red_pill.core.inbox import MinionInbox

			MinionInbox().resolve_report(f"signal_{name}")
			return
		manager = memory_manager
		if manager is None:
			from red_pill.memory import MemoryManager

			manager = MemoryManager()
		manager.evaporate_signals(name)
	except Exception as exc:  # best-effort: nunca tumba al plugin
		logger.debug(f"[Janitor] no se pudo enterrar la señal '{name}': {exc}")
