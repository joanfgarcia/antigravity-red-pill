import argparse
import asyncio
import os
import subprocess
import sys

sys.path.append(os.path.join(os.getcwd(), "src"))

from red_pill.memory import MemoryManager
from red_pill.rituals import (
	consolidation_ritual,
	dream_ritual,
	hygiene_ritual,
	lazarus_ritual,
	maintenance_ritual,
	resonance_ritual,
	swarm_ritual,
	thread_ritual,
	usp_ritual,
)

SETUP_TORCH_SCRIPT = os.path.join(os.path.dirname(__file__), "setup_torch.py")


def _check_cuda_drift() -> None:
	"""Run CUDA/torch drift detection. Non-blocking — issues are reported via pain signals."""
	try:
		result = subprocess.run(
			[sys.executable, SETUP_TORCH_SCRIPT, "--check"],
			capture_output=True,
			text=True,
			timeout=15,
		)
		if result.returncode != 0:
			print(f"[pulse] ⚠️  CUDA drift detected: {result.stdout.strip()}")
		else:
			print(f"[pulse] {result.stdout.strip()}")
	except Exception as e:
		print(f"[pulse] CUDA drift check skipped: {e}")


async def oneshot_pulse(cycle: str = "full") -> None:
	"""
	Execute a biological pulse cycle.

	Cycles:
		wake  — Social/connectivity rituals (hourly). Swarm, Lazarus, Resonance.
		sleep — Memory consolidation rituals (daily at 03:00). USP, Dream, Consolidation, Thread.
		full  — All rituals (legacy/manual use).
	"""

	print(f"Initiating Oneshot Pulse (Cycle: {cycle})...")

	# CUDA drift check — always runs, non-blocking
	_check_cuda_drift()

	mm = MemoryManager()

	# Maintenance always runs — system health checks (CUDA, Qdrant, Korsakoff)
	await maintenance_ritual(mm)

	# Wake rituals — social connectivity, swarm, hive sync
	if cycle in ("full", "wake"):
		await swarm_ritual(mm)
		await lazarus_ritual(mm)
		await resonance_ritual(mm)
		await hygiene_ritual(mm)

	# Sleep rituals — memory consolidation, oneiromancy, Ariadne's Thread
	if cycle in ("full", "sleep"):
		await usp_ritual(mm)
		await dream_ritual(mm)
		await consolidation_ritual(mm)
		await thread_ritual()

	print("Pulse complete. Returning to the void.")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Red Pill Sovereign Pulse")
	parser.add_argument(
		"--cycle",
		choices=["wake", "sleep", "full"],
		default="full",
		help="Biological cycle to execute: wake (hourly), sleep (03:00 daily), full (all rituals)",
	)
	args = parser.parse_args()
	asyncio.run(oneshot_pulse(cycle=args.cycle))
