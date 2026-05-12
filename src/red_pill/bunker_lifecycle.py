import logging
import subprocess
from pathlib import Path
from typing import Any, Dict

import psutil
import yaml

from red_pill.core.paths import get_bunker_root

logger = logging.getLogger(__name__)


def detect_hardware() -> Dict[str, Any]:
	"""Detects CPU, RAM, and basic GPU presence."""
	# RAM
	ram_info = psutil.virtual_memory()
	total_ram_gb = round(ram_info.total / (1024**3), 2)

	# CPU
	cpu_cores = psutil.cpu_count(logical=False) or 1
	cpu_threads = psutil.cpu_count(logical=True) or 1

	# GPU (Basic nvidia-smi probe)
	has_nvidia = False
	vram_gb = 0.0
	try:
		# Ask nvidia-smi for total memory of the first GPU
		result = subprocess.run(
			["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
		)
		if result.returncode == 0:
			lines = result.stdout.strip().split("\n")
			if lines and lines[0].isdigit():
				has_nvidia = True
				vram_gb = round(int(lines[0]) / 1024, 2)
	except FileNotFoundError:
		pass

	return {"ram_gb": total_ram_gb, "cpu_cores": cpu_cores, "cpu_threads": cpu_threads, "has_nvidia": has_nvidia, "vram_gb": vram_gb}


def profile_hardware() -> None:
	"""bunker init: Generates the bunker.profile.yaml based on hardware."""
	print("--- [BÜNKER PROFILING: DETECTING HARDWARE] ---")
	hw = detect_hardware()
	print(f"Total RAM: {hw['ram_gb']} GB")
	print(f"CPU: {hw['cpu_cores']} cores ({hw['cpu_threads']} threads)")

	if hw["has_nvidia"]:
		print(f"GPU: NVIDIA detected ({hw['vram_gb']} GB VRAM)")
	else:
		print("GPU: No NVIDIA GPU detected. Using CPU/NPU defaults.")

	# Calculate safe MemoryMax for Cgroups (Reserve 4GB for OS/Desktop)
	safe_memory_max = max(2.0, hw["ram_gb"] - 4.0)

	profile = {
		"hardware": {"memory_max_gb": round(safe_memory_max, 1), "workers": min(8, hw["cpu_cores"]), "cuda_enabled": hw["has_nvidia"]},
		"models": {"quantization": "INT2" if hw["has_nvidia"] and hw["vram_gb"] > 10 else "Q4_K_M"},
	}

	# Path is resolved relatively to the project root or workspace
	# Using the standard behavior for Red Pill
	workspace_root = str(get_bunker_root())
	profile_path = Path(workspace_root) / "bunker.profile.yaml"

	with open(profile_path, "w") as f:
		yaml.dump(profile, f, sort_keys=False)

	print(f"\n[OK] Declarative profile generated: {profile_path}")


def bunker_export() -> None:
	"""
	Sovereign Backup: Exports Qdrant, SQLite (w/ WAL checkpoint), .env, and plugins.
	Encrypts the output using pure-mls.
	"""
	print("--- [BÜNKER EXPORT: SOVEREIGN BACKUP] ---")
	print("1. Forcing SQLite PRAGMA wal_checkpoint(TRUNCATE)...")
	print("2. Decrypting Chronicle logs for flat text backup...")
	print("3. Capturing Qdrant Engine Snapshot...")
	print("4. Delegating sub-exports to Neon-Link and Plugins...")
	print("5. Generating manifest.json (Red-Pill, Python, Qdrant versions)...")
	print("6. Encrypting package to .mls via pure-mls cryptography...")
	print("\n[STUB] Export flow mapped. Awaiting implementation.")


def bunker_restore() -> None:
	"""
	Smart Restore: Interprets manifest.json and selectively rehydrates the system.
	"""
	print("--- [BÜNKER RESTORE: SMART REHYDRATION] ---")
	print("1. Decrypting .mls package via Sovereign Keys...")
	print("2. Validating manifest.json (Checking version mismatches)...")
	print("3. Executing selective extraction (Flags parsing)...")
	print("4. Delegating sub-restores to Neon-Link and Plugins...")
	print("5. Rebooting Bünker Daemons and syncing state...")
	print("\n[STUB] Restore flow mapped. Awaiting implementation.")


def handle_bunker(args) -> None:
	"""Dispatcher for 'bunker' CLI commands."""
	if args.bunker_cmd == "init":
		profile_hardware()
	elif args.bunker_cmd == "install":
		print("[NOT IMPLEMENTED] bunker install is under construction.")
	elif args.bunker_cmd == "update":
		print("[NOT IMPLEMENTED] bunker update is under construction.")
	elif args.bunker_cmd == "export":
		bunker_export()
	elif args.bunker_cmd == "restore":
		bunker_restore()
	else:
		print("[ERROR] Invalid bunker command.")
