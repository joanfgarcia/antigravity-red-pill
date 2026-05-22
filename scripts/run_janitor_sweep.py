import asyncio
import logging
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from red_pill.swarm.agents.janitor import JanitorMinion
from red_pill.swarm.orchestrator import GruOrchestrator

logging.basicConfig(level=logging.INFO)


async def run_sweep():
	print("--- [Swarm] Desplegando JanitorMinion para barrido de mantenimiento... ---")

	orchestrator = GruOrchestrator()
	results = await orchestrator.deploy_swarm("Execute daily sweep", [JanitorMinion()], days_to_keep=7)

	res = results[0]
	if res.status == "success":
		print("\n=== REPORTE DE JANITOR ===")
		print(f"Bases de datos de eventos purgadas: {res.result.get('db_events_purged', 0)}")
		print(f"Archivos temporales (scratch) eliminados: {res.result.get('scratch_files_purged', 0)}")
		print("==========================\n")
	else:
		print(f"[Error] Fallo en el Janitor: {res.error}")


if __name__ == "__main__":
	asyncio.run(run_sweep())
