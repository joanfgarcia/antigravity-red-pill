"""Purga y observabilidad del espejo canónico (`session_mirror`, AD-060).

Política conservadora: un alma con algún leg activo NUNCA pierde turnos; solo
se purgan almas sin leg activo cuyo último turno supera `retention_days`.

Toda tarea con TTL devuelve métricas y deja una señal de estado medible; si el
espejo crece por encima de los umbrales o quedan candidatos sin purgar, emite
señal de dolor. Regla de diseño: `docs/CORE/CONVENTIONS.md` §10.10.
"""

import json
import logging
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class SessionMirrorPurgePlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "session_mirror_purge"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		import red_pill.config as cfg
		from red_pill.session.mirror import SessionMirror

		app_cfg = cfg.get_config()
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		retention_days = float(plugin_cfg.get("retention_days", getattr(app_cfg, "SESSION_MIRROR_RETENTION_DAYS", 30)))
		growth_rows = int(plugin_cfg.get("growth_rows", getattr(app_cfg, "SESSION_MIRROR_GROWTH_ROWS", 200000)))
		growth_bytes = int(plugin_cfg.get("growth_bytes", getattr(app_cfg, "SESSION_MIRROR_GROWTH_BYTES", 536870912)))

		janitor.log(f"[Janitor] Running session_mirror_purge (retention={retention_days}d)...")
		mirror = SessionMirror()
		from red_pill.session.store import SessionRegistry

		registry = SessionRegistry(mirror.db_path)
		expired = registry.expire_idle_legs()
		before = mirror.stats(retention_days=retention_days)
		stubbed = mirror.stub_tool_results()
		purged = mirror.purge(registry, retention_days=retention_days)
		budget = mirror.enforce_budget()
		after = mirror.stats(retention_days=retention_days)
		metrics = {
			"session_mirror_rows_before": before["rows"],
			"session_mirror_rows_after": after["rows"],
			"session_mirror_rows_purged": purged["rows_purged"],
			"session_mirror_souls": after["souls"],
			"session_mirror_souls_purged": purged["souls_purged"],
			"session_mirror_dead_rows": after["dead_rows"],
			"session_mirror_orphan_rows": after["orphan_rows"],
			"session_mirror_undated_rows": after["undated_rows"],
			"session_mirror_unknown_age_souls": after["unknown_age_souls"],
			"session_mirror_bytes": after["db_bytes"] + after["wal_bytes"],
			"session_mirror_budget_bytes": after["budget_bytes"],
			"session_mirror_budget_pct": after["budget_pct"],
			"session_mirror_over_budget": after["over_budget"],
			"session_mirror_stub_rows": stubbed["rows_stubbed"],
			"session_mirror_stub_chars_saved": stubbed["chars_saved"],
			"session_mirror_emergency": bool(budget.get("emergency")),
			"session_mirror_rows_trimmed": int(budget.get("rows_trimmed") or 0),
			"session_registry_expired": expired,
			"session_mirror_retention_days": int(retention_days),
		}
		janitor.log(f"[Janitor] session_mirror_purge: {json.dumps(metrics, ensure_ascii=False)}")
		_emit_signals(kwargs.get("memory_manager"), metrics, after, growth_rows, growth_bytes)
		return metrics


def _emit_signals(memory_manager: Any, metrics: Dict[str, Any], after: Dict[str, Any], growth_rows: int, growth_bytes: int) -> None:
	"""Señal de estado (medible) + dolor solo si hay un problema real."""
	try:
		if memory_manager is None:
			from red_pill.memory import MemoryManager

			memory_manager = MemoryManager()
		memory_manager.inject_signal(
			name="session_mirror_stats",
			intensity=1.0,
			signal_type="status",
			source="Janitor",
			criticality="INFO",
			message=json.dumps(metrics, ensure_ascii=False),
		)
		problems = []
		if after["rows"] > growth_rows:
			problems.append(f"filas={after['rows']} > {growth_rows}")
		if after["db_bytes"] + after["wal_bytes"] > growth_bytes:
			problems.append(f"bytes={after['db_bytes'] + after['wal_bytes']} > {growth_bytes}")
		if after["expired_candidates"]:
			problems.append(f"candidatos_sin_purgar={after['expired_candidates']}")
		if problems:
			memory_manager.inject_signal(
				name="session_mirror_growth",
				intensity=4.0,
				signal_type="pain",
				source="Janitor",
				message="; ".join(problems),
			)
		import red_pill.config as cfg

		app_cfg = cfg.get_config()
		budget_pct = float(after.get("budget_pct") or 0.0)
		warn_pct = float(getattr(app_cfg, "SESSION_MIRROR_WARN_PCT", 80.0))
		emergency_pct = float(getattr(app_cfg, "SESSION_MIRROR_EMERGENCY_PCT", 95.0))
		if budget_pct >= warn_pct:
			memory_manager.inject_signal(
				name="session_mirror_budget",
				intensity=5.0 if budget_pct >= emergency_pct else 3.0,
				signal_type="pain",
				source="Janitor",
				message=(
					f"espejo al {budget_pct:.1f}% del presupuesto "
					f"({after['db_bytes'] + after['wal_bytes']}/{after['budget_bytes']} bytes)"
					+ (" — EMERGENCIA aplicada" if after.get("over_budget") else "")
				),
			)
	except Exception as e:
		logger.debug(f"[Janitor] session_mirror señal no inyectada: {e}")
