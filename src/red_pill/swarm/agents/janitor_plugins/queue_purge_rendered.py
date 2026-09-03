"""Purga de memory_queue gateada por el Memento (RFC-002 §4.4.2 / MUST 10, Fase 3).

Hoy nada borra filas de memory_queue (crecimiento sin límite). La regla del
RFC: una fila `completed` solo puede purgarse cuando el Memento ya la ha
renderizado. v1 conservadora: solo se purgan filas de los grupos de la fuente
`memory_queue` (mcp:<originator>:<día>) presentes en memento_registry.json y
más viejas que el margen — las filas de originators cubiertos por provider
stores (antigravity/claude_code/opencode) se dejan en paz: son pocas y su
verbatim canónico es el store, no la cola.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)

UNKNOWN_ORIGINATOR = "unknown"


class QueuePurgeRenderedPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "queue_purge_rendered"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		import red_pill.config as cfg
		from red_pill.core.paths import get_queue_dir
		from red_pill.memento.registry import MementoRegistry

		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		margin_days = int(plugin_cfg.get("margin_days", getattr(cfg, "MEMENTO_QUEUE_RETENTION_DAYS", 7)))
		db_path = kwargs.get("queue_db_path") or get_queue_dir() / "bunker_queue.db"
		registry_path = kwargs.get("registry_path")

		registry = MementoRegistry(path=registry_path) if registry_path else MementoRegistry()
		rendered_groups = set()
		for session_id, entry in registry.sessions_of("memory_queue").items():
			if entry.get("dir") and session_id.startswith("mcp:"):
				rendered_groups.add(session_id[len("mcp:") :])  # "<originator>:<AAAA-MM-DD>"

		if not rendered_groups:
			janitor.log("[Janitor] queue_purge_rendered: nada renderizado aún — sin purga.")
			return {"purged": 0}

		cutoff_day = (datetime.now(timezone.utc) - timedelta(days=margin_days)).date().isoformat()
		purged = 0
		try:
			con = sqlite3.connect(str(db_path), timeout=30.0)
			try:
				for group in sorted(rendered_groups):
					originator, _, day = group.rpartition(":")
					if not day or day >= cutoff_day:
						continue  # margen de seguridad: solo días ya fríos
					where = "originator IS NULL" if originator == UNKNOWN_ORIGINATOR else "originator = ?"
					params = [] if originator == UNKNOWN_ORIGINATOR else [originator]
					cursor = con.execute(
						f"DELETE FROM memory_queue WHERE status = 'completed' AND ({where}) AND date(created_at, 'unixepoch') = ?",
						params + [day],
					)
					purged += cursor.rowcount
				con.commit()
			finally:
				con.close()
		except sqlite3.Error as e:
			logger.warning(f"[Janitor] queue_purge_rendered failed: {e}")
			return {"purged": purged, "error": str(e)}

		janitor.log(f"[Janitor] queue_purge_rendered: {purged} fila(s) completed purgadas (grupos renderizados, >{margin_days}d).")
		return {"purged": purged, "margin_days": margin_days}
