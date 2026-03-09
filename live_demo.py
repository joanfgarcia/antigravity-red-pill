import asyncio
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.swarm.agents.oracle import OracleMinion
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.base import Minion

async def main():
	print("🚨 INICIANDO PROTOCOLO ENJAMBRE (MCP SWARM v5) 🚨\n")
	
	gru = GruOrchestrator()
	print(f"[*] Orquestador GRU en línea.")
	
	oracle = OracleMinion(id="o1")
	smith = SmithMinion(id="s1")
	print(f"[*] Minions instanciados: {oracle.name}, {smith.name}\n")
	
	print("[*] Desplegando enjambre en paralelo...")
	
	# Gru deploys Oracle to search memory and Smith to audit the current directory
	results = await gru.deploy_swarm(
		task="Auditar código fuente y buscar referencias a Antigravity en memoria",
		minions=[oracle, smith],
		path="."
	)
	
	print("\n✅ RESULTADOS DEL ENJAMBRE:\n")
	for res in results:
		print(f"🤖 Minion ID : {res.minion_id}")
		print(f"⏱️  Duración   : {res.duration}s")
		print(f"📊 Estado     : {res.status}")
		
		# Truncate result dictionary for readability
		import json
		res_str = json.dumps(res.result, indent=2, ensure_ascii=False)
		if len(res_str) > 500:
			res_str = res_str[:500] + "\n... [TRUNCADO]"
		print(f"📦 Resultado :\n{res_str}\n" + "-"*40 + "\n")

if __name__ == "__main__":
	asyncio.run(main())
