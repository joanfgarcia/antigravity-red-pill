import asyncio
import sys
import os

sys.path.append(os.path.join(os.getcwd(), "src"))

from red_pill.memory import MemoryManager
from red_pill.soul import SoulManager
from red_pill.heartbeat import LazarusPulse

async def oneshot_pulse():
    mem_mgr = MemoryManager()
    soul_mgr = SoulManager()
    pulse = LazarusPulse(mem_mgr, soul_mgr)
    
    print("Initiating Oneshot Lazarus Pulse...")
    await pulse._maintenance_ritual()
    await pulse._usp_ritual()
    await pulse._dream_ritual()
    await pulse._consolidation_ritual()
    await pulse._swarm_ritual()
    await pulse._lazarus_ritual()
    await pulse._resonance_ritual()
    print("Pulse complete. Returning to the void.")

if __name__ == "__main__":
    asyncio.run(oneshot_pulse())
