import asyncio

from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.orchestrator import GruOrchestrator


async def run_surgical_audit():
	print("--- RED PILL: SURGICAL LINE-BY-LINE FORENSICS (7B NEURAL SWEEP) ---")
	orchestrator = GruOrchestrator()
	smith = SmithMinion()

	import os

	# Dynamically determine project root
	project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

	# We pass 'super_deep_audit' to trigger the surgical mode
	results = await orchestrator.deploy_swarm("super_deep_audit", [smith], path=project_root)

	for res in results:
		if res.status == "success":
			print(f"\nFinal Security Score: {res.result['security_score']}/100")
			print(f"Files Scanned: {res.result['files_scanned']}")

			if res.result["findings"]:
				print("\n☢️ SURGICAL FORENSIC FINDINGS:")
				# Group findings by file
				from typing import Any, Dict, List
				findings_by_file: Dict[str, List[Dict[str, Any]]] = {}
				for f in res.result["findings"]:
					findings_by_file.setdefault(f["file"], []).append(f)

				for filename, file_findings in findings_by_file.items():
					print(f"\nFile: {filename}")
					for f in file_findings:
						print(f"  [Line {f['line']}] {f['msg']}")
			else:
				print("\n✅ Zero-Trust verified. No line-level vulnerabilities found by the 7B model.")
		else:
			print(f"Audit Error: {res.error}")


if __name__ == "__main__":
	asyncio.run(run_surgical_audit())
