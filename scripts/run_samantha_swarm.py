import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from red_pill.swarm.agents.samantha import SamanthaMinion
from red_pill.swarm.orchestrator import GruOrchestrator


async def run_analysis():
	chapter_path = "docs/LORE/novel/ALETH_CAPITULO_1.md"
	if not os.path.exists(chapter_path):

		print(f"Error: {chapter_path} not found.")
		return

	with open(chapter_path, "r", encoding="utf-8") as f:
		content = f.read()

	print("--- [Swarm] Desplegando SamanthaMinion para análisis narrativo... ---")

	orchestrator = GruOrchestrator()
	results = await orchestrator.deploy_swarm(content, [SamanthaMinion()])

	res = results[0]
	if res.status == "success":
		analysis = res.result.get("analysis")
		print("\n=== REPORTE DE SAMANTHA (vía Swarm) ===\n")
		print(analysis)
		print("\n========================================\n")

		from red_pill.core.paths import get_bunker_root

		reports_dir = os.path.join(get_bunker_root(), "reports")
		os.makedirs(reports_dir, exist_ok=True)
		report_path = os.path.join(reports_dir, "SAMANTHA_REPORT_CH1.md")
		with open(report_path, "w", encoding="utf-8") as rf:
			rf.write("# Reporte de Análisis Narrativo: Capítulo 1\n")
			rf.write("**Analista:** Samantha (Hermes-3-Llama-3.1-8B / Local Engine via Swarm/SIP)\n")
			rf.write("**Fecha:** 2026-06-26\n\n")
			rf.write(analysis)
		print(f"[Success] Report saved to {report_path}")
	else:
		print(f"[Error] Fallo en el Swarm: {res.error}")


if __name__ == "__main__":
	asyncio.run(run_analysis())
