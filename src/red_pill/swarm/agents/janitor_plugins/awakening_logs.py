import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from red_pill.core.paths import get_awakening_dir
from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)

# Cada despertar escribe su propio `YYYYMMDD_HHMM.log` (hora local, ver
# get_awakening_log_path). La fecha va en el nombre, así que se usa ESA para la
# edad — no el mtime, que `git` puede tocar al restaurar/mover el desk.
_AWAKENING_LOG_RE = re.compile(r"^(\d{8})_\d{4}\.log$")


class AwakeningLogsPlugin(JanitorPlugin):
	"""Purga los logs de despertar más antiguos que `days_to_keep`.

	No "rota" (los logs ya están rotados por despertar): borra los que superan
	el TTL. Configurable en `plugins.awakening_logs.days_to_keep`; default 30
	días. Solo toca ficheros `YYYYMMDD_HHMM.log`; nunca `notes/`, `done/` ni
	`README.md`.
	"""

	@property
	def name(self) -> str:
		return "awakening_logs"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running awakening_logs plugin...")
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		days_to_keep = int(plugin_cfg.get("days_to_keep", 30))

		awakening_dir = get_awakening_dir()
		if not awakening_dir.is_dir():
			janitor.log(f"[Janitor] Awakening dir {awakening_dir} not found. Skipping.")
			return {"awakening_logs_purged": 0}

		cutoff = datetime.now() - timedelta(days=days_to_keep)
		purged = 0
		for item in awakening_dir.glob("*.log"):
			ts = self._log_timestamp(item)
			if ts is None or ts >= cutoff:
				continue
			try:
				item.unlink()
				purged += 1
				janitor.log(f"[Janitor] Deleted old awakening log: {item.name}")
			except Exception as e:
				logger.error(f"[Janitor] Failed to delete awakening log {item}: {e}")

		if purged:
			janitor.log(f"[Janitor] awakening_logs: {purged} log(s) older than {days_to_keep}d purged.")
		return {"awakening_logs_purged": purged}

	def _log_timestamp(self, path: Path) -> Optional[datetime]:
		match = _AWAKENING_LOG_RE.match(path.name)
		if match:
			try:
				return datetime.strptime(match.group(1), "%Y%m%d")
			except ValueError:
				pass
		# Fallback: mtime, por si el esquema de nombres cambiara.
		try:
			return datetime.fromtimestamp(path.stat().st_mtime)
		except Exception:
			return None
