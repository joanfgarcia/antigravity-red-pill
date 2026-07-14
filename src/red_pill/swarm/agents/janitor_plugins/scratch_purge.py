import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class ScratchPurgePlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "scratch_purge"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running scratch_purge plugin...")
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		days_to_keep = plugin_cfg.get("days_to_keep", 7)

		scratch_path = Path.home() / "tmp" / "scratch"
		purged_files = 0

		if scratch_path.exists() and scratch_path.is_dir():
			now = datetime.now().timestamp()
			cutoff_time = now - (days_to_keep * 86400)

			try:
				for item in scratch_path.iterdir():
					try:
						if item.stat().st_mtime < cutoff_time:
							if item.is_file():
								item.unlink()
							elif item.is_dir():
								shutil.rmtree(item)
							purged_files += 1
							janitor.log(f"[Janitor] Purged scratch item: {item.name}")
					except Exception as e:
						logger.error(f"[Janitor] Failed to delete {item}: {e}")
						janitor.log(f"[Janitor] Error deleting {item.name}: {e}")
			except Exception as e:
				logger.error(f"[Janitor] Failed to read scratch folder {scratch_path}: {e}")
				janitor.log(f"[Janitor] Error reading scratch folder: {e}")
		else:
			janitor.log(f"[Janitor] Scratch folder {scratch_path} not found. Skipping scratch purge.")

		return {"scratch_files_purged": purged_files}
