import asyncio

from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.orchestrator import GruOrchestrator


async def run_industrial_audit():
	print("--- RED PILL: INDUSTRIAL SECURITY FORENSICS (DEEP MODE) ---")
	orchestrator = GruOrchestrator()
	smith = SmithMinion()

	import os

	# Dynamically determine project root
	project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	results = await orchestrator.deploy_swarm("industrial_audit", [smith], path=project_root)

	for res in results:
		if res.status == "success":
			print(f"\nFinal Security Score: {res.result['security_score']}/100")
			print(f"Files Scanned: {res.result['files_scanned']}")

			if res.result["findings"]:
				print("\n⚠️ CRITICAL/TECHNICAL FINDINGS FOUND:")
				for f in res.result["findings"]:
					icon = "☢️" if f["severity"] == "CRITICAL" else "⚠️"
					print(f"{icon} [{f['file']}:{f['line']}] {f['msg']}")
			else:
				print("\n✅ No critical findings detected even by SLM Neural Forensics.")
		else:
			print(f"Audit Error: {res.error}")


if __name__ == "__main__":
	asyncio.run(run_industrial_audit())
