import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class SqliteInteractionsArchiverPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "sqlite_interactions_archiver"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running sqlite_interactions_archiver plugin...")
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		days_to_keep = plugin_cfg.get("days_to_keep", 30)

		from red_pill.core.paths import get_aleth_core_root, get_db_dir

		db_path = get_db_dir() / "bunker.db"
		archived_count = 0

		if not db_path.exists():
			janitor.log(f"[Janitor] Database {db_path} not found. Skipping interactions archiving.")
			return {"sqlite_interactions_archived": 0}

		try:
			conn = sqlite3.connect(str(db_path))
			cursor = conn.cursor()

			# Check if interactions table exists
			cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interactions'")
			if not cursor.fetchone():
				conn.close()
				janitor.log("[Janitor] Interactions table does not exist. Skipping archiving.")
				return {"sqlite_interactions_archived": 0}

			cutoff = datetime.utcnow() - timedelta(days=days_to_keep)
			cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

			cursor.execute(
				"SELECT user_prompt, agent_response, timestamp, model FROM interactions WHERE timestamp < ?",
				(cutoff_str,),
			)
			rows = cursor.fetchall()

			if rows:
				archive_dir = get_aleth_core_root() / "history"
				archive_dir.mkdir(parents=True, exist_ok=True)
				archive_file = archive_dir / "universal_history.jsonl"

				with open(archive_file, "a") as f:
					for row in rows:
						item = {
							"timestamp": row[2],
							"user_prompt": row[0],
							"agent_response": row[1],
							"model": row[3] or "unknown",
						}
						f.write(json.dumps(item) + "\n")
						archived_count += 1

				cursor.execute("DELETE FROM interactions WHERE timestamp < ?", (cutoff_str,))
				conn.commit()
				janitor.log(f"[Janitor] Archived {archived_count} old interactions from SQLite to universal_history.jsonl")
			else:
				janitor.log("[Janitor] No old interactions to archive.")

			conn.close()
		except Exception as e:
			logger.error(f"[Janitor] Failed to archive SQLite interactions: {e}")
			janitor.log(f"[Janitor] Error archiving interactions: {e}")

		return {"sqlite_interactions_archived": archived_count}
