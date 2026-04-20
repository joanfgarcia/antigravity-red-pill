import abc
import enum
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class PluginScope(enum.Enum):
	MEMORY = "memory"
	TELEMETRY = "telemetry"
	COGNITION = "cognition"
	STORAGE = "storage"
	SYSTEM_EVENT = "system_event"
	BACKGROUND = "background"

class Priority(enum.IntEnum):
	FIRST = 0
	HIGH = 25
	NORMAL = 50
	LOW = 75
	LAST = 100

class CircuitBreak(Exception):
	pass

class SovereignPlugin(abc.ABC):

	def __init__(self, name: str, version: str, directory: Path):
		self.name = name
		self.version = version
		self.directory = directory
		self._is_active = False
		self.config = self._load_config()

	def _load_config(self) -> Dict[str, Any]:
		"""Carga la configuración del plugin priorizando el directorio soberano IA_DIR."""
		import json

		from red_pill import config as cfg

		# 1. Intentar ruta soberana: {IA_DIR}/plugins/{name}/{name}.json
		sovereign_path = Path(cfg.IA_DIR) / "plugins" / self.name / f"{self.name}.json"

		# 2. Fallback a ruta de fuentes (Legacy/Default)
		fallback_path = self.directory / f"{self.name}.json"

		config_path = sovereign_path if sovereign_path.exists() else fallback_path

		if not config_path.exists():
			logger.info(f"[PluginBase] Creando config vacía para '{self.name}' en la ruta soberana {sovereign_path}")
			sovereign_path.parent.mkdir(parents=True, exist_ok=True)
			with open(sovereign_path, "w", encoding="utf-8") as f:
				json.dump({}, f, indent=4)
			return {}

		try:
			with open(config_path, "r", encoding="utf-8") as f:
				return json.load(f)
		except Exception as e:
			logger.error(f"[PluginBase] Error cargando config para plugin {self.name} desde {config_path}: {e}")
			return {}


	@property
	@abc.abstractmethod
	def scopes(self) -> List[PluginScope]:
		pass

	@property
	def requested_permissions(self) -> List[str]:
		"""Manifiesto formal de los recursos requeridos (Qdrant, Red, Archivos, etc)."""
		return []

	@property
	def priority(self) -> Priority:
		return Priority.NORMAL

	@abc.abstractmethod
	async def init(self) -> None:
		pass

	@abc.abstractmethod
	async def activate(self) -> None:
		pass

	@abc.abstractmethod
	async def hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:
		pass

	@abc.abstractmethod
	async def deactivate(self) -> None:
		"""Detiene el flujo sin destruir datos (ej. stop listeners)."""
		pass

	@abc.abstractmethod
	async def uninstall(self, purge: bool = False) -> None:
		"""
		Desregistro del plugin. Si purge=True, aniquila colecciones y datos.
		Si purge=False, deja la infraestructura en disco intacta.
		"""
		pass

	@abc.abstractmethod
	async def export_state(self) -> Dict[str, Any]:
		"""
		Enganche con `export_soul`. Devuelve todo el estado soberano del plugin
		para ser empaquetado en el archivo maestro de persistencia del Bünker.
		"""
		pass

	def validate_sovereignty(self) -> bool:
		required = ["README.md", "TECHNICAL.md", "USER_MANUAL.md"]
		return all((self.directory / doc).exists() for doc in required)

class PluginRegistry:

	def __init__(self):
		self._plugins: Dict[str, SovereignPlugin] = {}
		self._routing_table: Dict[PluginScope, List[SovereignPlugin]] = {
			scope: [] for scope in PluginScope
		}

	def register(self, plugin: SovereignPlugin) -> None:
		if not plugin.validate_sovereignty():
			raise RuntimeError(f"Fallo de Soberanía documental en: {plugin.name}")

		# --- SOVEREIGN AUDIT ENGINE ---
		permissions = getattr(plugin, "requested_permissions", [])
		if not permissions:
			logger.info(f"[AUDIT] Soberanía Validada: {plugin.name} (Modo Seguro - Sin Permisos Peligrosos)")
		else:
			for perm in permissions:
				logger.warning(f"[AUDIT] {plugin.name} requiere escalada: '{perm}'. Aprobado (Trusted MVP).")
		# ------------------------------

		self._plugins[plugin.name] = plugin

		for scope in plugin.scopes:
			self._routing_table[scope].append(plugin)
			self._routing_table[scope].sort(key=lambda p: p.priority.value)

		logger.info(f"Registrado [Oculto]: {plugin.name} v{plugin.version} (Prioridad: {plugin.priority.name})")

	async def activate_all(self) -> None:
		for plugin in self._plugins.values():
			if not plugin._is_active:
				await plugin.init()
				await plugin.activate()
				plugin._is_active = True

	async def emit_hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:
		interested_plugins = self._routing_table[scope]
		mutated_payload = payload.copy()

		for plugin in interested_plugins:
			if not plugin._is_active:
				continue

			try:
				mutated_payload = await plugin.hook(scope, mutated_payload)
			except CircuitBreak:
				logger.warning(f"Circuit Breaker activado por [{plugin.name}] en scope {scope.name}. Halting pipeline.")
				break
			except Exception as e:
				logger.error(f"Plugin Error [{plugin.name}]: {e}")

		return mutated_payload
