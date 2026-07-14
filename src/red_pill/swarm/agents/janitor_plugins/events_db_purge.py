import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class EventsDbPurgePlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "events_db_purge"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running events_db_purge plugin...")
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		days_to_keep = plugin_cfg.get("days_to_keep", 7)

		events_db_path = Path.home() / ".local" / "share" / "neon-link" / "events.db"
		purged = 0

		if events_db_path.exists():
			try:
				conn = sqlite3.connect(events_db_path)
				cursor = conn.cursor()
				cutoff_date = (datetime.utcnow() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d %H:%M:%S")

				cursor.execute(
					"DELETE FROM inbox WHERE status IN ('PROCESSED', 'DEAD', 'DELIVERED_BACKGROUND') AND created_at < ?",
					(cutoff_date,),
				)
				inbox_deleted = cursor.rowcount

				cursor.execute("DELETE FROM outbox WHERE status IN ('SENT', 'DEAD') AND created_at < ?", (cutoff_date,))
				outbox_deleted = cursor.rowcount

				cursor.execute("DELETE FROM processed_firebase_messages WHERE processed_at < ?", (cutoff_date,))
				processed_fb_deleted = cursor.rowcount

				conn.commit()
				conn.close()

				purged = inbox_deleted + outbox_deleted + processed_fb_deleted
				janitor.log(f"[Janitor] Purged {purged} stale events from {events_db_path.name}")
			except Exception as e:
				logger.error(f"[Janitor] Failed to purge events.db: {e}")
				janitor.log(f"[Janitor] Error during events_db_purge execution: {e}")
		else:
			janitor.log(f"[Janitor] Database {events_db_path} not found. Skipping DB purge.")

		return {"db_events_purged": purged}
