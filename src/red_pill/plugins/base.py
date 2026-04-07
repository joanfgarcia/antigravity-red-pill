import json
import logging
import os
from typing import Any, Dict

from red_pill import config as cfg

logger = logging.getLogger(__name__)

class RedPillPlugin:
	"""
	Sovereign Base Class for all Red Pill Plugins.
	Enforces Strict Configuration isolation in <IA_DIR>/plugins/.
	"""

	plugin_name: str = "base_plugin"

	def __init__(self) -> None:
		self.config = self._load_config()

	def _load_config(self) -> Dict[str, Any]:
		"""Loads configuration strictly from <IA_DIR>/plugins/<plugin_name>/<plugin_name>.json"""
		plugin_dir = os.path.join(cfg.IA_DIR, "plugins", self.plugin_name)
		os.makedirs(plugin_dir, exist_ok=True)

		config_path = os.path.join(plugin_dir, f"{self.plugin_name}.json")

		if not os.path.exists(config_path):
			logger.info(f"[PluginBase] Creating empty config for '{self.plugin_name}' at {config_path}")
			with open(config_path, "w", encoding="utf-8") as f:
				json.dump({}, f, indent=4)
			return {}

		try:
			with open(config_path, "r", encoding="utf-8") as f:
				return json.load(f)
		except Exception as e:
			logger.error(f"[PluginBase] Failed to load config for plugin {self.plugin_name}: {e}")
			return {}
