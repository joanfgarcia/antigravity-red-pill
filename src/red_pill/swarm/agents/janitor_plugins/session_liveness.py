import logging
import time
from typing import Any, Dict

from red_pill.core.session_liveness import get_sessions_live_dir, parse_filename
from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class SessionLivenessPlugin(JanitorPlugin):
	"""Purga los latidos de sesión (`.start`/`.end`) con `mtime` > TTL.

	RFC-DESPERTAR-001, P4. La retención (por defecto `SESSION_LIVENESS_TTL_H`,
	48 h) es **distinta** del umbral de "activo ahora" (`SESSION_ACTIVE_MIN`):
	aquí solo se limpia lo viejo; lo fresco del turno nunca se toca.
	"""

	@property
	def name(self) -> str:
		return "session_liveness"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running session_liveness plugin...")
		import red_pill.config as cfg

		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		ttl_h = int(plugin_cfg.get("ttl_h", getattr(cfg.get_config(), "SESSION_LIVENESS_TTL_H", 48)))

		live = get_sessions_live_dir()
		if not live.is_dir():
			return {"session_liveness_purged": 0}

		cutoff = time.time() - ttl_h * 3600
		purged = 0
		for item in live.iterdir():
			if not item.is_file() or parse_filename(item.name) is None:
				continue
			try:
				if item.stat().st_mtime < cutoff:
					item.unlink()
					purged += 1
			except Exception as e:
				logger.error(f"[Janitor] Failed to delete liveness file {item}: {e}")

		if purged:
			janitor.log(f"[Janitor] session_liveness: {purged} latido(s) > {ttl_h}h purgados.")
		return {"session_liveness_purged": purged}
