"""Purga de memory_queue (RFC-002 §4.4.2 / MUST 10, Fase 3).

La cola no es un archivo: es **el buffer del mood**. Solo alimenta el drenaje a
`interaction_memories` (TTL 72 h) y al afecto léxico (ventana de 180 min); el
verbatim canónico de una conversación es el store del proveedor, que el Memento
ya renderiza. Por eso la purga se decide por dos cosas — **qué es la fila** y
**cuánto pesa en el mood** — y no por «¿lo tiene Memento?».

v1 solo purgaba los grupos de la fuente `memory_queue` (`mcp:<originator>:<día>`)
porque «las filas de provider stores son pocas». Medido el 2026-11-14: 1.430
filas, **1.134 de opencode** — la premisa caducó y la cola crecía sin techo.

v2 (2026-11-14, decisión del Operador) añade el pase por voz. Sin voz del
Operador (aviso de job, bloque del arnés, encargo de subagente, despertar
headless): fuera **sin mirar la edad**, porque esa fila no debió entrar nunca.
Con su voz: se conserva `margin_days` y después se va.

Medido antes del pase: 616 filas, de las que 148 no eran su voz y 300 ya habían
caducado para el mood. La regla «viejo + origen» se descartó por peligrosa: la
sesión `pi` `01a1a1a1…` estaba en la cola y no en el registro — la evidencia de
renderizado protegía la única copia, no la edad. Ese caso protegido sigue
cubierto por el pase `mcp:` de v1.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)

UNKNOWN_ORIGINATOR = "unknown"

_CHUNK = 500


class QueuePurgeRenderedPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "queue_purge_rendered"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		import red_pill.config as cfg
		from red_pill.core.operator_voice import extract as extract_operator_voice
		from red_pill.core.paths import get_queue_dir
		from red_pill.memento.registry import MementoRegistry

		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		margin_days = int(plugin_cfg.get("margin_days", getattr(cfg, "MEMENTO_QUEUE_RETENTION_DAYS", 7)))
		db_path = kwargs.get("queue_db_path") or get_queue_dir() / "bunker_queue.db"
		registry_path = kwargs.get("registry_path")
		dry_run = bool(kwargs.get("dry_run", False))

		registry = MementoRegistry(path=registry_path) if registry_path else MementoRegistry()
		rendered_groups = set()
		for session_id, entry in registry.sessions_of("memory_queue").items():
			if entry.get("dir") and session_id.startswith("mcp:"):
				rendered_groups.add(session_id[len("mcp:") :])  # "<originator>:<AAAA-MM-DD>"

		cutoff_day = (datetime.now(timezone.utc) - timedelta(days=margin_days)).date().isoformat()
		cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=margin_days)).timestamp()
		purged_groups = 0
		purged_no_voice = 0
		purged_expired = 0
		try:
			con = sqlite3.connect(str(db_path), timeout=30.0)
			try:
				# Pase A — grupos MCP-only: su única copia ES el Memento renderizado.
				for group in sorted(rendered_groups):
					originator, _, day = group.rpartition(":")
					if not day or day >= cutoff_day:
						continue  # margen de seguridad: solo días ya fríos
					where = "originator IS NULL" if originator == UNKNOWN_ORIGINATOR else "originator = ?"
					params = [] if originator == UNKNOWN_ORIGINATOR else [originator]
					sql = "SELECT COUNT(*)" if dry_run else "DELETE"
					sql += f" FROM memory_queue WHERE status = 'completed' AND ({where}) AND date(created_at, 'unixepoch') = ?"
					if dry_run:
						purged_groups += con.execute(sql, params + [day]).fetchone()[0]
					else:
						purged_groups += con.execute(sql, params + [day]).rowcount

				# Pase B — la voz del Operador: sin ella no es una fila del mood.
				rows = con.execute("SELECT id, prompt, created_at FROM memory_queue WHERE status = 'completed'").fetchall()
				sin_voz, caducadas = [], []
				for row_id, prompt, created_at in rows:
					if extract_operator_voice(prompt) is None:
						sin_voz.append(str(row_id))
					elif float(created_at or 0) < cutoff_ts:
						caducadas.append(str(row_id))
				purged_no_voice, purged_expired = len(sin_voz), len(caducadas)
				if not dry_run:
					for ids in (sin_voz, caducadas):
						for start in range(0, len(ids), _CHUNK):
							chunk = ids[start : start + _CHUNK]
							marks = ",".join("?" * len(chunk))
							con.execute(f"DELETE FROM memory_queue WHERE id IN ({marks})", chunk)
					con.commit()
			finally:
				con.close()
		except sqlite3.Error as e:
			logger.warning(f"[Janitor] queue_purge_rendered failed: {e}")
			return {"purged": purged_groups, "error": str(e)}

		total = purged_groups + purged_no_voice + purged_expired
		detalle = f"{purged_groups} por grupo mcp, {purged_no_voice} sin voz del Operador, {purged_expired} caducadas (>{margin_days}d)"
		prefijo = "[Janitor] queue_purge_rendered (dry-run)" if dry_run else "[Janitor] queue_purge_rendered"
		janitor.log(f"{prefijo}: {total} fila(s) purgables ({detalle})." if dry_run else f"{prefijo}: {total} fila(s) purgadas ({detalle}).")
		return {
			"purged": total,
			"purged_groups": purged_groups,
			"purged_no_voice": purged_no_voice,
			"purged_expired": purged_expired,
			"margin_days": margin_days,
			"dry_run": dry_run,
		}
