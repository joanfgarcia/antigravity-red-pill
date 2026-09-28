"""TTL backstop de `interaction_memories` (RFC-002 §4.4 / S3, Fase 3).

El Sleep ya auto-drena el buffer al consolidar; esto solo barre lo que el
drenaje deja atrás (failed_ids que hoy quedan para siempre, noches con la
VRAM llena). El almacenamiento raw duradero es Memento — Qdrant conserva solo
la ventana caliente.

Guardarraíl: el TTL debe superar la ventana del pre-heating
(PRE_HEATING_LOOKBACK_HOURS, única fuente de verdad desde que el hardcode 48h
del tier-2 de 11_pre_heating.py se alineó a la config) — si no, el plugin se
niega a purgar. Los puntos llevan el epoch en `timestamp` (memory.py:513); se
filtra también `created_at` por si generaciones antiguas lo usaron.
"""

import logging
import time
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class InteractionTTLPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "interaction_ttl"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		from qdrant_client.http import models

		import red_pill.config as cfg
		from red_pill.memory import MemoryManager

		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})
		ttl_hours = int(plugin_cfg.get("ttl_hours", getattr(cfg, "INTERACTION_MEMORIES_TTL_HOURS", 72)))
		floor = int(getattr(cfg, "PRE_HEATING_LOOKBACK_HOURS", 48))
		if ttl_hours <= floor:
			janitor.log(f"[Janitor] interaction_ttl SKIPPED: TTL {ttl_hours}h no supera la ventana del pre-heating ({floor}h).")
			return {"purged": 0, "skipped": "ttl_below_preheating_window"}

		cutoff = time.time() - ttl_hours * 3600
		mem = kwargs.get("memory_manager") or MemoryManager()
		collection = "interaction_memories"
		if not mem.client.collection_exists(collection):
			return {"purged": 0}

		stale_filter = models.Filter(
			should=[
				models.FieldCondition(key="timestamp", range=models.Range(lt=cutoff)),
				models.FieldCondition(key="created_at", range=models.Range(lt=cutoff)),
			]
		)

		# Purge gate (SW_PURGE_GATE_ENABLED): once Sleep no longer drains the buffer,
		# this TTL is the SOLE purger. Purge by age alone would drop raw turns whose
		# session was never rendered into Memento (chronicle down/late). Gate: only
		# purge points whose session is present in `memento_registry`. Points without
		# `session_id` are NOT purged (can't verify) — the max-age backstop handles them.
		if bool(getattr(cfg, "SW_PURGE_GATE_ENABLED", False)):
			from red_pill.memento.registry import MementoRegistry

			registry_path = kwargs.get("registry_path")
			registry = MementoRegistry(path=registry_path) if registry_path else MementoRegistry()
			rendered = set()
			# state["registry"] es anidado: {source: {session_id: entry}}, y el
			# session_id del registry lleva prefijo de fuente ("opencode:ses_x").
			# El buffer guarda el id crudo ("ses_x"), así que indexamos ambos.
			for source, sessions in registry.state.get("registry", {}).items():
				for sid in sessions:
					sid = str(sid)
					rendered.add(sid)
					if ":" in sid:
						rendered.add(sid.split(":", 1)[1])
					rendered.add(f"{source}:{sid}")

			to_delete: set = set()
			offset = None
			while True:
				points, offset = mem.client.scroll(collection, scroll_filter=stale_filter, limit=500, offset=offset, with_payload=True)
				for p in points:
					meta = (p.payload or {}).get("metadata") or {}
					sid = meta.get("session_id")
					if sid and str(sid) in rendered:
						to_delete.add(str(p.id))
				if offset is None:
					break

			# Tope duro de edad (D18/F4): lo NO renderizado más viejo que el cap se
			# purga igualmente (el buffer no puede crecer sin fin), y se emite una
			# señal de dolor para que el operador sepa que el chronicle va atrasado.
			hard_cutoff = time.time() - int(getattr(cfg, "INTERACTION_MAX_AGE_DAYS", 30)) * 86400
			hard_filter = models.Filter(
				should=[
					models.FieldCondition(key="timestamp", range=models.Range(lt=hard_cutoff)),
					models.FieldCondition(key="created_at", range=models.Range(lt=hard_cutoff)),
				]
			)
			orphaned = 0
			offset = None
			while True:
				points, offset = mem.client.scroll(collection, scroll_filter=hard_filter, limit=500, offset=offset, with_payload=True)
				for p in points:
					sid = ((p.payload or {}).get("metadata") or {}).get("session_id")
					if not (sid and str(sid) in rendered):
						orphaned += 1
					to_delete.add(str(p.id))
				if offset is None:
					break

			ids = list(to_delete)
			if ids:
				mem.client.delete(collection, points_selector=models.PointIdsList(points=ids), wait=True)
			if orphaned:
				try:
					mem.inject_signal(
						name="interaction_unrendered_purged",
						intensity=4.0,
						signal_type="pain",
						source="Janitor",
						message=f"{orphaned} turnos sin renderizar purgados por el tope de {getattr(cfg, 'INTERACTION_MAX_AGE_DAYS', 30)}d (chronicle atrasado).",
					)
				except Exception as _e:
					logger.debug(f"interaction_ttl: señal no inyectada: {_e}")
			janitor.log(f"[Janitor] interaction_ttl (gated): {len(ids)} purgados ({orphaned} sin renderizar).")
			return {"purged": len(ids), "orphaned": orphaned, "ttl_hours": ttl_hours, "gate": True}

		stale = mem.client.count(collection, count_filter=stale_filter, exact=True).count
		if stale:
			mem.client.delete(collection, points_selector=models.FilterSelector(filter=stale_filter), wait=True)
		janitor.log(f"[Janitor] interaction_ttl: {stale} punto(s) más viejos de {ttl_hours}h purgados del buffer.")
		return {"purged": stale, "ttl_hours": ttl_hours}
