import logging
from typing import Optional

import pluggy

from . import hookspecs

logger = logging.getLogger(__name__)

_pm: Optional[pluggy.PluginManager] = None

def get_plugin_manager() -> pluggy.PluginManager:
	"""Returns the singleton PluginManager for Red-Pill."""
	global _pm
	if _pm is None:
		_pm = pluggy.PluginManager("red_pill")
		_pm.add_hookspecs(hookspecs)

		# Load plugins natively
		from .cloud_sync import CloudSyncPlugin
		from .gmail_watcher import GmailWatcherPlugin
		_pm.register(CloudSyncPlugin())
		_pm.register(GmailWatcherPlugin())

		logger.info("[PluginManager] Initialized and plugins registered.")
	return _pm

