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
	import sqlite3
	import os
	import platformdirs
	import shutil
	import tarfile
	import time
	from red_pill.soul import SoulManager
	from red_pill.utils.vault import SoulCryptographer
	
	print("--- [BÜNKER EXPORT: SOVEREIGN BACKUP] ---")
	
	timestamp = time.strftime("%Y%m%d_%H%M%S")
	export_dir = os.path.join(str(get_bunker_root()), "backups", "export")
	os.makedirs(export_dir, exist_ok=True)
	
	tar_path = os.path.join(export_dir, f"TOTAL_SOVEREIGN_KIT_{timestamp}.tar.gz")
	staging_dir = os.path.join(export_dir, f"staging_{timestamp}")
	os.makedirs(staging_dir, exist_ok=True)
	
	print("1. Forcing SQLite PRAGMA wal_checkpoint(TRUNCATE)...")
	dbs_to_backup = [
		os.path.join(str(get_bunker_root()), "storage", "queue", "bunker_queue.db"),
		os.path.join(str(get_bunker_root()), "storage", "queue", "minion_inbox.db"),
		os.path.join(platformdirs.user_data_dir("neon-link"), "events.db")
	]
	
	for db_path in dbs_to_backup:
		if os.path.exists(db_path):
			try:
				conn = sqlite3.connect(db_path)
				conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
				conn.close()
				dest = os.path.join(staging_dir, os.path.basename(db_path))
				shutil.copy2(db_path, dest)
			except Exception as e:
				print(f"[FAIL] Could not checkpoint/copy {db_path}: {e}")
				
	print("2. Capturing Qdrant Engine Snapshot & Generating manifest.json...")
	soul = SoulManager()
	soul.backup_qdrant(timestamp)
	soul.create_manifest(timestamp)
	
	qdrant_backup_dir = os.path.join(soul.backup_root, "qdrant")
	for f in os.listdir(qdrant_backup_dir):
		if timestamp in f and (f.endswith(".snapshot") or f.endswith(".json")):
			shutil.copy2(os.path.join(qdrant_backup_dir, f), staging_dir)
			
	print("3. Delegating sub-exports to Plugins (.env secrets)...")
	red_pill_env = os.path.join(platformdirs.user_config_dir("red-pill"), ".env")
	if os.path.exists(red_pill_env):
		shutil.copy2(red_pill_env, os.path.join(staging_dir, "red_pill.env"))
		
	neon_env = os.path.join(platformdirs.user_config_dir("neon-link"), ".env")
	if os.path.exists(neon_env):
		shutil.copy2(neon_env, os.path.join(staging_dir, "neon_link.env"))
		
	print("4. Packing Tarball...")
	with tarfile.open(tar_path, "w:gz") as tar:
		for root, _, files in os.walk(staging_dir):
			for file in files:
				file_path = os.path.join(root, file)
				tar.add(file_path, arcname=file)
				
	shutil.rmtree(staging_dir)
	
	print("5. Encrypting package to .mls via pure-mls cryptography...")
	try:
		cryptographer = SoulCryptographer()
		encrypted_path = cryptographer.encrypt_kit(tar_path)
		if encrypted_path:
			os.remove(tar_path)
			print(f"\n[OK] SOVEREIGN EXPORT COMPLETE: {encrypted_path}")
		else:
			print(f"\n[WARNING] MLS Encryption returned None. Kit at: {tar_path}")
	except Exception as e:
		print(f"\n[WARNING] MLS Encryption failed or unavailable: {e}. Unencrypted kit at: {tar_path}")


def bunker_restore(target_path: str = None) -> None:
	"""
	Smart Restore: Interprets manifest.json and selectively rehydrates the system.
	"""
	import os
	import platformdirs
	import shutil
	import tarfile
	from red_pill.soul import SoulManager
	from red_pill.utils.vault import SoulCryptographer

	print("--- [BÜNKER RESTORE: SMART REHYDRATION] ---")
	export_dir = os.path.join(str(get_bunker_root()), "backups", "export")
	
	if not target_path:
		if not os.path.exists(export_dir):
			print("[ERROR] No backups directory found.")
			return
		mls_files = [os.path.join(export_dir, f) for f in os.listdir(export_dir) if f.endswith(".mls")]
		if not mls_files:
			print("[ERROR] No .mls backup found to restore.")
			return
		target_path = max(mls_files, key=os.path.getctime)
		
	print(f"1. Decrypting .mls package: {os.path.basename(target_path)}")
	cryptographer = SoulCryptographer()
	decrypted_tar = cryptographer.decrypt_kit(target_path)
	if not decrypted_tar:
		print("[FAIL] Decryption failed or legacy format.")
		return
		
	staging_dir = os.path.join(export_dir, "restore_staging")
	if os.path.exists(staging_dir):
		shutil.rmtree(staging_dir)
	os.makedirs(staging_dir)
	
	print("2. Extracting kit...")
	with tarfile.open(decrypted_tar, "r:gz") as tar:
		tar.extractall(path=staging_dir)
		
	print("3. Restoring SQLite Queues and Event DBs...")
	# Map extracted files back to system paths
	restore_map = {
		"bunker_queue.db": os.path.join(str(get_bunker_root()), "storage", "queue", "bunker_queue.db"),
		"minion_inbox.db": os.path.join(str(get_bunker_root()), "storage", "queue", "minion_inbox.db"),
		"events.db": os.path.join(platformdirs.user_data_dir("neon-link"), "events.db"),
		"red_pill.env": os.path.join(platformdirs.user_config_dir("red-pill"), ".env"),
		"neon_link.env": os.path.join(platformdirs.user_config_dir("neon-link"), ".env")
	}
	
	for extracted_file, dest_path in restore_map.items():
		src_path = os.path.join(staging_dir, extracted_file)
		if os.path.exists(src_path):
			os.makedirs(os.path.dirname(dest_path), exist_ok=True)
			shutil.copy2(src_path, dest_path)
			print(f"  -> Restored {extracted_file}")
			
	print("4. Rehydrating Qdrant Memory (Vector Cortex)...")
	soul = SoulManager()
	soul.restore_soul(staging_dir, commit=True)
	
	print("5. Cleaning up ephemeral decrypted state...")
	os.remove(decrypted_tar)
	shutil.rmtree(staging_dir)
	
	print("\n[OK] SOVEREIGN RESTORE COMPLETE. Rebooting Bünker Daemons is recommended.")


def bunker_export_keys() -> None:
	"""
	Extracts the Master Identity (MLS Keys & Vault State) into a raw tarball.
	The user MUST store this securely offline (e.g., USB drive).
	"""
	import os
	import platformdirs
	import tarfile
	import time
	from red_pill.core.paths import get_bunker_root

	print("--- [BÜNKER MASTER KEY EXPORT] ---")
	config_dir = platformdirs.user_config_dir("red-pill")
	keys_dir = os.path.join(config_dir, "keys")
	vault_state = os.path.join(config_dir, "vault_group.state")
	
	if not os.path.exists(keys_dir):
		print("[ERROR] No Cryptographic Keys found to export.")
		return
		
	timestamp = time.strftime("%Y%m%d_%H%M%S")
	export_dir = os.path.join(str(get_bunker_root()), "backups")
	os.makedirs(export_dir, exist_ok=True)
	
	tar_path = os.path.join(export_dir, f"SOVEREIGN_MASTER_KEYS_{timestamp}.tar.gz")
	
	with tarfile.open(tar_path, "w:gz") as tar:
		tar.add(keys_dir, arcname="keys")
		if os.path.exists(vault_state):
			tar.add(vault_state, arcname="vault_group.state")
			
	print(f"\n[CRITICAL WARNING] Master Keys exported to: {tar_path}")
	print("ANYONE with this file can decrypt your Soul Kits. MOVE IT TO A SECURE OFFLINE USB DRIVE IMMEDIATELY.")


def bunker_uninstall() -> None:
	"""
	Wipes the Sovereign environment from the host, keeping ONLY backups.
	Requires 6-digit confirmation. Master Keys are explicitly preserved.
	"""
	import os
	import random
	import platformdirs
	import shutil
	from red_pill.core.paths import get_bunker_root

	print("\n!!! [WARNING] BÜNKER UNINSTALL INITIATED !!!")
	print("This action will obliterate the active Red-Pill environment:")
	print(" - Qdrant Vector Data")
	print(" - SQLite Queues and Event DBs")
	print(" - .env configs and Plugins")
	print("\n[NOTE] Backups and Cryptographic MASTER KEYS will NOT be deleted.")
	
	if os.getenv("BUNKER_FORCE_UNINSTALL") == "1":
		print("\n[CI/CD OVERRIDE] BUNKER_FORCE_UNINSTALL=1 detected. Bypassing MFA confirmation.")
	else:
		challenge_code = f"{random.randint(100000, 999999):06d}"
		print(f"\nTo proceed, type the following 6-digit authorization code: {challenge_code}")
		user_input = input("> ")
		
		if user_input.strip() != challenge_code:
			print("\n[ABORTED] Authorization code mismatch. The Bünker remains intact.")
			return
		
	print("\n[AUTHORIZED] Initiating Purge Protocol...")
	
	# 1. Purge Qdrant Collections
	print("-> Wiping Qdrant Vector Cortex...")
	try:
		from red_pill.soul import SoulManager
		import requests
		import red_pill.config as cfg
		
		soul = SoulManager()
		headers = {"api-key": cfg.QDRANT_API_KEY} if cfg.QDRANT_API_KEY else {}
		colls = soul._get_collections()
		for coll in colls:
			requests.delete(f"{cfg.QDRANT_URL}/collections/{coll}", headers=headers, timeout=5)
			print(f"   Deleted collection: {coll}")
	except Exception as e:
		print(f"   [!] Failed to wipe Qdrant. Is it running? Error: {e}")
		
	# 2. Preserve Keys
	config_dir = platformdirs.user_config_dir("red-pill")
	keys_safe_dir = os.path.join(str(get_bunker_root()), "backups", "keys_vault_temp")
	os.makedirs(keys_safe_dir, exist_ok=True)
	
	if os.path.exists(os.path.join(config_dir, "keys")):
		shutil.copytree(os.path.join(config_dir, "keys"), os.path.join(keys_safe_dir, "keys"))
	if os.path.exists(os.path.join(config_dir, "vault_group.state")):
		shutil.copy2(os.path.join(config_dir, "vault_group.state"), os.path.join(keys_safe_dir, "vault_group.state"))
		
	# 3. Wipe Paths
	paths_to_wipe = [
		os.path.join(platformdirs.user_data_dir("neon-link")),
		config_dir,  # This wipes the keys too
		os.path.join(str(get_bunker_root()), "storage"),
		os.path.join(str(get_bunker_root()), "plugins")
	]
	
	for path in paths_to_wipe:
		if os.path.exists(path):
			try:
				shutil.rmtree(path)
				print(f"-> Purged Directory: {path}")
			except Exception as e:
				print(f"   [!] Failed to purge {path}: {e}")
				
	# 4. Restore Keys to Config Dir
	os.makedirs(config_dir, exist_ok=True)
	if os.path.exists(os.path.join(keys_safe_dir, "keys")):
		shutil.copytree(os.path.join(keys_safe_dir, "keys"), os.path.join(config_dir, "keys"))
	if os.path.exists(os.path.join(keys_safe_dir, "vault_group.state")):
		shutil.copy2(os.path.join(keys_safe_dir, "vault_group.state"), os.path.join(config_dir, "vault_group.state"))
	shutil.rmtree(keys_safe_dir)
	print("-> Cryptographic Identity Preserved.")
				
	print("\n[OK] SOVEREIGN PURGE COMPLETE. The entity has been erased from this host.")


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
	elif args.bunker_cmd == "uninstall":
		bunker_uninstall()
	elif args.bunker_cmd == "export-keys":
		bunker_export_keys()
	else:
		print("[ERROR] Invalid bunker command.")
