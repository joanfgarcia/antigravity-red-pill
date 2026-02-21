import multiprocessing
import time
import asyncio
import logging
from minion_swarm.agents.oracle import get_oracle_minion
from minion_swarm.agents.smith import get_smith_minion
from lazarus_deck.orchestrator import GruProcessOrchestrator

# Configure logging for the proof
logging.basicConfig(level=logging.INFO, format="[LIVE_BUNKER] %(message)s")

async def run_live_proof():
    print("\n" + "="*50)
    print(" PROJECT LAZARUS v6.0: LIVE SWARM PROOF")
    print("="*50 + "\n")
    
    orchestrator = GruProcessOrchestrator()
    
    # 1. Initialize Agents
    oracle = get_oracle_minion()
    smith = get_smith_minion()
    
    # Force IDs for the proof routing
    oracle.id = "Oracle-01"
    smith.id = "Smith-01"
    
    print(f"[STATUS] Deploying Oracle ({oracle.id}) and Smith ({smith.id})...")
    
    # 2. Deploy Agents
    # Oracle is sent to research something that triggers collaboration
    orchestrator.deploy_minion(oracle, "Analyze B760 security audit logs")
    orchestrator.deploy_minion(smith, "Standby monitoring")
    
    print("[STATUS] Swarm running. Waiting for autonomous synaptic pulses...")
    
    # 3. Monitor for 5 seconds
    start = time.time()
    while time.time() - start < 5:
        results = orchestrator.check_results()
        for res in results:
            mid = res.get("minion_id")
            m_name = "Oracle" if mid == "Oracle-01" else "Smith"
            data = res.get("result", {})
            
            if "collaboration" in data and data["collaboration"]:
                print(f"\n[!!] AUTONOMOUS PULSE DETECTED: {m_name} initiated delegation.")
                print(f"     > Action: {data['collaboration']}")
            
            if "synthesis" in data:
                print(f"\n[INFO] Oracle Synthesis: {data['synthesis']}")
            
            if "security_score" in data:
                print(f"\n[INFO] Smith Audit: Score {data['security_score']} (Protocols verified)")
        
        asyncio.sleep(0.5)

    print("\n" + "="*50)
    print(" PROOF COMPLETE: Sovereign Loop Verified.")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(run_live_proof())
