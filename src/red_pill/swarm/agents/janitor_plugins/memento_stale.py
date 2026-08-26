"""Detector de staleness del pase agéntico Memento (RFC-002 §4.5.1, Fase 3.5).

Si `memento/index.md` cambió tras un re-render (hash del registry ≠ hash con el
que se destiló), los `source_lines` de distill/refine apuntan a rangos muertos.
Este plugin detecta el desajuste comparando dos campos del propio registry
(cero I/O de ficheros) y emite la señal muted `memento_stale_distill` al
MinionInbox; la cura sigue el precedente knowledge_graph_stale: la rama del
`auto_heal_ritual` relanza `memento_agentic.py --heal-stale` (regeneración
completa, jamás parcheo).
"""

import json
import logging
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class MementoStalePlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "memento_stale"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		from red_pill.memento.agentic import pending_agentic
		from red_pill.memento.registry import MementoRegistry

		registry_path = kwargs.get("registry_path")
		registry = MementoRegistry(path=registry_path) if registry_path else MementoRegistry()
		stale = [(source, session_id) for source, session_id, reason in pending_agentic(registry) if reason == "stale"]
		if not stale:
			janitor.log("[Janitor] memento_stale: distill/refine al día.")
			return {"stale": 0}

		try:
			from red_pill.memory import MemoryManager

			mem = kwargs.get("memory_manager") or MemoryManager()
			mem.inject_signal(
				name="memento_stale_distill",
				intensity=5.0,
				signal_type="pain",
				source="Janitor",
				muted=True,  # → MinionInbox, donde el auto_heal_ritual lo recoge
				message=json.dumps([f"{source}|{session_id}" for source, session_id in stale], ensure_ascii=False),
				originator=f"memento_stale ({len(stale)} sesiones con distill/refine desactualizados)",
			)
		except Exception as sig_err:
			logger.warning(f"[Janitor] Failed to inject memento_stale_distill signal: {sig_err}")

		janitor.log(f"[Janitor] memento_stale: {len(stale)} sesión(es) con distill/refine stale — señal emitida.")
		return {"stale": len(stale)}
