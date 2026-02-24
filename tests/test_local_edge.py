import asyncio
import os
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.swarm.agents.compressor import CompressorMinion

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

if __name__ == "__main__":
    asyncio.run(test_local_compression())
