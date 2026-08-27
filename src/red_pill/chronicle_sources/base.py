"""Base y descubrimiento de los Chronicle Source Plugins (pipeline de ARCHIVO).

NO confundir con `red_pill.metabolism.chronicle` (ChronicleExtractorPlugin):
aquello snatchea trayectorias hacia staging para alimentar la CONSOLIDACIÓN;
esto enumera y carga conversaciones completas para que `chronicle_daily.py`
las archive en `archive_memories`. Mismo patrón agnóstico que JanitorMinion:
añadir un orquestador nuevo (IDE/CLI) = un archivo nuevo en este paquete,
sin tocar el pipeline.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ChronicleSourcePlugin(ABC):
	"""Una fuente de conversaciones archivables (Antigravity, Claude Code, opencode...)."""

	name: str = "base"

	# Prefijo del session_id lógico en archive_memories. Antigravity queda SIN
	# prefijo porque sus puntos ya acuñados usan el cascade_id desnudo y el evict
	# de copias previas casa por session_id; toda fuente nueva DEBE prefijar para
	# que la clave lógica (session_id, sequence_index, role) no colisione entre IDEs.
	session_prefix: str = ""

	def qualify(self, conversation_id: str) -> str:
		"""session_id namespaced con el que la conversación vive en archive_memories."""
		return f"{self.session_prefix}{conversation_id}"

	def is_enabled(self) -> bool:
		import red_pill.config as cfg

		return self.name in getattr(cfg, "CHRONICLE_ARCHIVE_SOURCES", ["antigravity"])

	def workspace_of(self, conversation_id: str) -> Optional[str]:
		"""Workspace de la conversación si la fuente lo conoce (RFC-002 Q6); None si no aplica."""
		return None

	def export_raw(self, conversation_id: str, dest_dir: "Path") -> Optional["Path"]:
		"""Copia verbatim provider-nativa a `dest_dir` (el `raw/` del Memento, RFC-002 §4.2).

		El raw es la copia de respaldo y punto único de backup del operador: con
		él el árbol se regenera desde cero sin provider stores. None si la fuente
		no lo soporta.
		"""
		return None

	def load_raw(self, raw_file: "Path") -> List[Dict[str, Any]]:
		"""Renormaliza mensajes desde una copia `raw/` previa (regeneración sin store)."""
		raise NotImplementedError(f"Source '{self.name}' does not support raw reload")

	@abstractmethod
	def discover(self) -> List[Tuple[str, int]]:
		"""[(conversation_id, step_count)] de todas las conversaciones visibles de la fuente."""

	@abstractmethod
	def load(self, conversation_id: str) -> List[Dict[str, Any]]:
		"""Mensajes normalizados [{role, content, timestamp}] de una conversación."""


def discover_source_plugins(only_enabled: bool = True) -> List[ChronicleSourcePlugin]:
	"""Auto-descubre las subclases de ChronicleSourcePlugin de este paquete."""
	import red_pill.chronicle_sources as sources_pkg

	plugins: List[ChronicleSourcePlugin] = []
	for _importer, mod_name, _ispkg in pkgutil.iter_modules(sources_pkg.__path__):
		if mod_name.startswith("_") or mod_name == "base":
			continue
		try:
			module = importlib.import_module(f"red_pill.chronicle_sources.{mod_name}")
			for attr_name in dir(module):
				attr = getattr(module, attr_name)
				if isinstance(attr, type) and issubclass(attr, ChronicleSourcePlugin) and attr is not ChronicleSourcePlugin:
					plugins.append(attr())
		except Exception as e:
			logger.error(f"[ChronicleSources] Failed to load source module '{mod_name}': {e}")

	if only_enabled:
		plugins = [p for p in plugins if p.is_enabled()]
	# Orden determinista: mismo barrido cada noche, logs comparables.
	plugins.sort(key=lambda p: p.name)
	return plugins
