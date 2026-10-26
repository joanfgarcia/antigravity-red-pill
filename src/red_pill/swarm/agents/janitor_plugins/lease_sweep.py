"""Watchdog de leases: marca `stalled` los vencidos (B-01L / B-02).

El runner late el lease de compactación (`session compact`); si el proceso muere
o se cuelga, este plugin del Janitor lo detecta por `idle_ttl`/`max_wall` y lo
deja `stalled` para que el Operador/runner decida. No borra turnos ni aborta el
espejo.
"""

from typing import Any, Dict

from red_pill.session.lease import LeaseStore
from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin


class LeaseSweepPlugin(JanitorPlugin):
	"""Marca `stalled` los leases activos cuyo heartbeat/techo venció."""

	@property
	def name(self) -> str:
		return "lease_sweep"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running lease_sweep plugin...")
		expired = LeaseStore().sweep(mark_stalled=True)
		if expired:
			janitor.log(f"[Janitor] lease_sweep: {len(expired)} lease(s) marcados stalled.")
		return {"lease_sweep_stalled": len(expired)}
