import asyncio
import os

import pytest

from red_pill.swarm.agents.compressor import CompressorMinion
from red_pill.swarm.orchestrator import GruOrchestrator


@pytest.mark.anyio
async def test_local_compression():
	print("--- RED PILL: LOCAL COMPRESSION TEST ---")
	orchestrator = GruOrchestrator()

	if orchestrator.is_local_ready():
		print("✅ Local Edge Node detected.")
	else:
		print("❌ Local Edge Node NOT detected.")
		return

	compressor = CompressorMinion()
	verbose_text = (
		"Hola JARVIS, necesito que por favor revises el código de la base de datos "
		"porque creo que hay un problema con la persistencia cuando se reinicia el sistema. "
		"Básicamente lo que pasa es que los datos no se guardan correctamente en el disco "
		"y me gustaría saber si podrías proponer una solución técnica para esto."
	)

	print(f"Original text length: {len(verbose_text)}")
	results = await orchestrator.deploy_swarm("compress", [compressor], text=verbose_text)

	for res in results:
		if res.status == "success":
			print(f"Status: {res.status}")
			print(f"Compressed Output:\n{res.result['compressed_prompt']}")
		else:
			print(f"Error: {res.error}")

	print("\n--- TEST: ORACLE SYNTHESIS ---")
	from red_pill.swarm.agents.oracle import OracleMinion

	oracle = OracleMinion()
	# Search for something that might be in memory, or just a general query
	query = "Sovereign Identity Protocol"
	oracle_results = await orchestrator.deploy_swarm(query, [oracle])

	for res in oracle_results:
		if res.status == "success":
			print(f"Oracle Synthesis:\n{res.result['synthesis']}")
		else:
			print(f"Oracle Error: {res.error}")

	print("\n--- TEST: SMITH AUDIT + SLM FORENSICS ---")
	from red_pill.swarm.agents.smith import SmithMinion

	smith = SmithMinion()
	# Audit the local directory including the vulnerable sample
	path = os.path.join(os.getcwd(), "tests")
	smith_results = await orchestrator.deploy_swarm("audit", [smith], path=path)

	for res in smith_results:
		if res.status == "success":
			print(f"Security Score: {res.result['security_score']}")
			print(f"Findings: {len(res.result['findings'])}")
			for f in res.result["findings"]:
				print(f"- {f['file']}:{f['line']} -> {f['msg']}")
				if "slm_validation" in f:
					print(f"  [SLM Validation]: {f['slm_validation']}")
		else:
			print(f"Smith Error: {res.error}")


if __name__ == "__main__":
	asyncio.run(test_local_compression())
