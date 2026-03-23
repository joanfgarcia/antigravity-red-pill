import asyncio
import os
import subprocess
import sys

sys.path.append(os.path.join(os.getcwd(), "src"))

from red_pill.heartbeat import LazarusPulse
from red_pill.memory import MemoryManager
from red_pill.soul import SoulManager

SETUP_TORCH_SCRIPT = os.path.join(os.path.dirname(__file__), "setup_torch.py")


def _check_cuda_drift() -> None:
	"""Run CUDA/torch drift detection. Non-blocking — issues are reported via pain signals."""
	try:
		result = subprocess.run(
			[sys.executable, SETUP_TORCH_SCRIPT, "--check"],
			capture_output=True, text=True, timeout=15,
		)
		if result.returncode != 0:
			print(f"[pulse] ⚠️  CUDA drift detected: {result.stdout.strip()}")
		else:
			print(f"[pulse] {result.stdout.strip()}")
	except Exception as e:
		print(f"[pulse] CUDA drift check skipped: {e}")


async def oneshot_pulse():
	print("Initiating Oneshot Lazarus Pulse...")

	# CUDA drift check — runs every hour, non-blocking
	_check_cuda_drift()

	mem_mgr = MemoryManager()
	soul_mgr = SoulManager()
	pulse = LazarusPulse(mem_mgr, soul_mgr)

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

