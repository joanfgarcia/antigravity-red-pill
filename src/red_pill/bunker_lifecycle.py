import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
import yaml

from red_pill.core.paths import (
	get_bunker_root,
	get_config_dir,
	get_data_dir,
	get_neon_link_config_dir,
	get_neon_link_data_dir,
	get_neon_link_db_path,
	get_queue_dir,
)

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


def update_services_manifest(project_root: Path) -> None:
	"""Updates the runtime services.yaml with the latest examples/services.yaml template."""
	import shutil

	config_dir = get_config_dir()
	config_dir.mkdir(parents=True, exist_ok=True)
	runtime_manifest = config_dir / "services.yaml"
	template_manifest = project_root / "examples" / "services.yaml"

	if template_manifest.exists():
		if runtime_manifest.exists():
			with open(template_manifest, "r") as tf, open(runtime_manifest, "r") as rf:
				t_content = tf.read()
				r_content = rf.read()

			if t_content != r_content:
				backup_manifest = config_dir / "services.yaml.bak"
				shutil.copy2(runtime_manifest, backup_manifest)
				print(f"   [INFO] Stashing backup of old services.yaml to {backup_manifest}")
				shutil.copy2(template_manifest, runtime_manifest)
				print("   [OK] services.yaml updated to latest version.")
		else:
			shutil.copy2(template_manifest, runtime_manifest)
			print("   [OK] services.yaml bootstrapped to user config.")


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
	import os
	import shutil
	import sqlite3
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
		str(get_queue_dir() / "bunker_queue.db"),
		str(get_queue_dir() / "minion_inbox.db"),
		str(get_neon_link_db_path()),
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
	red_pill_env = os.path.join(get_config_dir(), ".env")
	if os.path.exists(red_pill_env):
		shutil.copy2(red_pill_env, os.path.join(staging_dir, "red_pill.env"))

	neon_env = os.path.join(get_neon_link_config_dir(), ".env")
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


def bunker_restore(target_path: Optional[str] = None, kem_path: Optional[str] = None, sig_path: Optional[str] = None) -> None:
	"""
	Smart Restore: Interprets manifest.json and selectively rehydrates the system.
	"""
	import os
	import shutil
	import tarfile

	from red_pill.soul import SoulManager
	from red_pill.utils.vault import SoulCryptographer

	print("--- [BÜNKER RESTORE: SMART REHYDRATION] ---")

	config_dir = str(get_config_dir())
	if kem_path or sig_path:
		print("0. Overriding Cryptographic Identity...")
		os.makedirs(config_dir, exist_ok=True)
		if kem_path and os.path.exists(kem_path):
			dest_seed = os.path.join(config_dir, "vault.seed")
			shutil.copy2(kem_path, dest_seed)
			print(f"  -> Imported KEM (Seed): {kem_path}")
		if sig_path and os.path.exists(sig_path):
			dest_state = os.path.join(config_dir, "vault_group.state")
			shutil.copy2(sig_path, dest_state)
			print(f"  -> Imported Signature State: {sig_path}")

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
		tar.extractall(path=staging_dir, filter="data")

	print("3. Restoring SQLite Queues and Event DBs...")
	# Map extracted files back to system paths
	restore_map = {
		"bunker_queue.db": str(get_queue_dir() / "bunker_queue.db"),
		"minion_inbox.db": str(get_queue_dir() / "minion_inbox.db"),
		"events.db": str(get_neon_link_db_path()),
		"red_pill.env": os.path.join(get_config_dir(), ".env"),
		"neon_link.env": os.path.join(get_neon_link_config_dir(), ".env"),
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
	import tarfile
	import time

	print("--- [BÜNKER MASTER KEY EXPORT] ---")
	config_dir = str(get_config_dir())
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
	import shutil

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
		import requests

		import red_pill.config as cfg
		from red_pill.soul import SoulManager

		soul = SoulManager()
		headers = {"api-key": cfg.QDRANT_API_KEY} if cfg.QDRANT_API_KEY else {}
		colls = soul._get_collections()
		for coll in colls:
			requests.delete(f"{cfg.QDRANT_URL}/collections/{coll}", headers=headers, timeout=5)
			print(f"   Deleted collection: {coll}")
	except Exception as e:
		print(f"   [!] Failed to wipe Qdrant. Is it running? Error: {e}")

	# 2. Preserve Keys
	config_dir = str(get_config_dir())
	keys_safe_dir = os.path.join(str(get_bunker_root()), "backups", "keys_vault_temp")
	os.makedirs(keys_safe_dir, exist_ok=True)

	if os.path.exists(os.path.join(config_dir, "keys")):
		shutil.copytree(os.path.join(config_dir, "keys"), os.path.join(keys_safe_dir, "keys"))
	if os.path.exists(os.path.join(config_dir, "vault_group.state")):
		shutil.copy2(os.path.join(config_dir, "vault_group.state"), os.path.join(keys_safe_dir, "vault_group.state"))

	# 3. Wipe Paths
	paths_to_wipe = [
		str(get_neon_link_data_dir()),
		config_dir,  # This wipes the keys too
		str(get_data_dir()),
		os.path.join(str(get_bunker_root()), "plugins"),
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


def bunker_install() -> None:
	"""
	bunker install:
	1. Check if .env exists in the config directory; copy the template from the project if missing.
	2. Bootstrap Qdrant collections (schemas, indices, and version engrams).
	3. Execute schedule_pulse.py to register systemd units and timers.
	4. Trigger download of default GGUF models.
	"""
	import os
	import shutil

	print("--- [BÜNKER INSTALL: SELF-ASSEMBLY BOOTSTRAP] ---")

	config_dir = get_config_dir()
	config_dir.mkdir(parents=True, exist_ok=True)
	env_file = config_dir / ".env"
	bunker_root = get_bunker_root()
	if (bunker_root / ".env.example").exists() or os.getenv("PYTEST_CURRENT_TEST"):
		project_root = bunker_root
	else:
		project_root = Path(__file__).parent.parent.parent

	if not env_file.exists():
		template = project_root / ".env.example"
		if template.exists():
			print(f"1. Bootstrapping .env configuration from template: {template}")
			shutil.copy2(template, env_file)
			env_file.chmod(0o600)
		else:
			print(f"[FAIL] Could not find .env template at {template}")
			return
	else:
		print("1. Active .env configuration detected. Skipping template bootstrap.")

	print("1.5 Bootstrapping services.yaml manifest...")
	update_services_manifest(project_root)

	print("2. Bootstrapping Qdrant schemas and collections...")
	try:
		import sys

		venv_python = project_root / ".venv" / "bin" / "python"
		if not venv_python.exists():
			venv_python = Path(sys.executable)

		res = subprocess.run([str(venv_python), "-m", "red_pill.cli", "seed"], cwd=str(project_root), capture_output=True, text=True)
		if res.returncode == 0:
			print("   [OK] Collections and schemas seeded successfully.")
		else:
			print(f"   [FAIL] Seed failed: {res.stderr}")
	except Exception as e:
		print(f"   [FAIL] Seed exception: {e}")

	print("3. Registering Bünker systemd timers...")
	try:
		schedule_script = project_root / "scripts" / "schedule_pulse.py"
		if schedule_script.exists():
			res = subprocess.run(
				[str(venv_python), str(schedule_script), "--interval-hours", "1"], cwd=str(project_root), capture_output=True, text=True
			)
			if res.returncode == 0:
				print("   [OK] Systemd timers and services registered.")
			else:
				print(f"   [FAIL] Timer registration failed: {res.stderr}")
		else:
			print(f"   [FAIL] schedule_pulse.py not found at {schedule_script}")
	except Exception as e:
		print(f"   [FAIL] Timer registration exception: {e}")

	print("4. Fetching default GGUF model files...")
	try:
		download_script = project_root / "scripts" / "download_slm.py"
		if download_script.exists():
			res = subprocess.run([str(venv_python), str(download_script)], cwd=str(project_root), capture_output=True, text=True)
			if res.returncode == 0:
				print("   [OK] Default GGUF models downloaded.")
			else:
				print(f"   [FAIL] Model download failed: {res.stderr}")
		else:
			print("   [INFO] No download_slm.py script found. Skipping model download.")
	except Exception as e:
		print(f"   [FAIL] Model download exception: {e}")

	print("\n[OK] BÜNKER INSTALLATION PROCEDURES CONCLUDED.")


def parse_changelog_release(changelog: str) -> Optional[Dict[str, str]]:
	"""Extract the latest release (version, date, codename, headlines, previous) from CHANGELOG.md.

	The codename is never invented at update time: it is whatever the release
	author wrote in the heading — `## [X.Y.Z] - YYYY-MM-DD (Codename)` — which
	ships versioned with the code.
	"""
	import re

	releases = re.findall(r"^## \[([^\]]+)\] - (\S+)(?:\s*\(([^)]*)\))?", changelog, re.M)
	if not releases:
		return None
	version, date, codename = releases[0]
	previous = releases[1][0] if len(releases) > 1 else ""

	first_heading = changelog.find(f"## [{version}]")
	next_heading = changelog.find(f"## [{previous}]") if previous else len(changelog)
	body = changelog[first_heading:next_heading]
	sections = [re.sub(r"^[\W_]+", "", t).strip() for t in re.findall(r"^### (.+)$", body, re.M)]

	return {
		"version": version,
		"date": date,
		"codename": codename.strip(),
		"features": "; ".join(s for s in sections if s),
		"previous": previous,
	}


def refresh_protocol_version_engram(project_root: Path) -> bool:
	"""Upsert the PROTOCOL VERSION singleton engram from CHANGELOG.md (update step 3.5).

	Dev machines never run `bunker update` (they live on the working tree), so this
	is also callable standalone: `python -m red_pill.bunker_lifecycle` refreshes it.
	"""
	try:
		changelog_path = project_root / "CHANGELOG.md"
		if not changelog_path.exists():
			print("   [SKIP] CHANGELOG.md not found; PROTOCOL VERSION engram untouched.")
			return False
		release = parse_changelog_release(changelog_path.read_text(encoding="utf-8"))
		if not release or not release["version"]:
			print("   [WARN] Could not parse a release heading from CHANGELOG.md.")
			return False

		text = (
			f"PROTOCOL VERSION: Red Pill Protocol v{release['version']}. Released {release['date']}."
			+ (f" Codename: {release['codename']}." if release["codename"] else "")
			+ (f" Key features: {release['features']}." if release["features"] else "")
			+ (f" Previous stable: v{release['previous']}." if release["previous"] else "")
			+ " This engram MUST be updated on every version bump."
		)

		from red_pill.memory import MemoryManager
		from red_pill.seed import ID_PROTOCOL_VERSION

		MemoryManager().add_memory(
			collection="directive_memories",
			text=text,
			importance=10.0,
			intensity=10.0,
			metadata={"category": "operational_law", "type": "protocol_version"},
			force_immune=True,
			point_id=ID_PROTOCOL_VERSION,
		)
		print(f"   [OK] PROTOCOL VERSION engram sealed at v{release['version']} ({release['codename'] or 'no codename'}).")
		return True
	except Exception as e:
		print(f"   [WARN] PROTOCOL VERSION engram refresh failed: {e}")
		return False


def bunker_update() -> None:
	"""
	bunker update:
	1. Run git pull on the sharing repository.
	2. Run uv sync --frozen to align virtual environment dependencies.
	2.5/2.6. Refresh the services manifest, IDE anchors and MCP config.
	2.7. Regenerate the background LLM daemon (setup_background_model.sh) and restart it.
	2.8. Redeploy skills to the agent skills dir.
	3. Run any pending database migrations.
	4. Reload systemd daemons (systemctl --user daemon-reload).
	"""
	import os
	import shutil

	from red_pill.core.paths import get_bunker_root

	bunker_root = get_bunker_root()
	if (bunker_root / ".env.example").exists() or os.getenv("PYTEST_CURRENT_TEST"):
		project_root = bunker_root
	else:
		project_root = Path(__file__).parent.parent.parent

	print("--- [BÜNKER UPDATE: SOVEREIGN SYNCHRONIZATION] ---")

	if (project_root / ".git").exists():
		print("1. Pulling latest code changes from origin...")
		res = subprocess.run(["git", "pull"], cwd=str(project_root), capture_output=True, text=True)
		if res.returncode == 0:
			print(f"   [OK] Code synchronized:\n{res.stdout.strip()}")
		else:
			print(f"   [FAIL] Git pull failed: {res.stderr}")
	else:
		print("1. No Git repository detected. Skipping code synchronization.")

	print("2. Aligning virtual environment dependencies via uv...")
	uv_bin = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
	uv_ran = False
	if uv_bin and os.path.exists(uv_bin):
		res = subprocess.run([uv_bin, "sync", "--frozen"], cwd=str(project_root), capture_output=True, text=True)
		if res.returncode == 0:
			print("   [OK] Dependencies synchronized.")
			uv_ran = True
		else:
			print(f"   [FAIL] Dependency sync failed: {res.stderr}")

	if not uv_ran:
		try:
			res = subprocess.run(["uv", "sync", "--frozen"], cwd=str(project_root), capture_output=True, text=True)
			if res.returncode == 0:
				print("   [OK] Dependencies synchronized.")
			else:
				print(f"   [FAIL] Dependency sync failed: {res.stderr}")
		except FileNotFoundError:
			print("   [FAIL] 'uv' binary not found. Skipping dependency alignment.")

	print("2.5 Updating services.yaml manifest...")
	update_services_manifest(project_root)
	print("2.6 Refreshing IDE anchors + MCP config (auto-detect all IDEs)...")
	try:
		import sys as _sys

		dispatcher_py = project_root / ".venv" / "bin" / "python"
		if not dispatcher_py.exists():
			dispatcher_py = Path(_sys.executable)
		# Use the unified dispatcher (detects Claude Code, OpenCode, Antigravity, etc.)
		res = subprocess.run(
			[str(dispatcher_py), "scripts/inject_cli.py", "--redpill-dir", str(project_root)],
			cwd=str(project_root),
			capture_output=True,
			text=True,
		)
		if res.returncode == 0:
			print(f"   [OK] IDE anchors and MCP config refreshed:\n{res.stdout.strip()}")
		else:
			print(f"   [WARN] IDE injection dispatcher returned non-zero: {res.stderr[:300]}")
	except Exception as e:
		print(f"   [WARN] Anchor/MCP refresh skipped: {e}")

	print("2.7 Regenerating background LLM daemon + restarting service...")
	# The dual-bind daemon (run_dual_bind.py) is GENERATED by setup_background_model.sh,
	# not shipped as a tracked file — a bare `git pull` never updates it. Re-run the
	# script so daemon-level changes (tool-calling chat_format switch, device cascade)
	# reach an existing install; the script also restarts redpill-llm.service.
	try:
		setup_script = project_root / "scripts" / "setup_background_model.sh"
		if setup_script.exists() and shutil.which("bash"):
			res = subprocess.run(["bash", str(setup_script)], cwd=str(project_root), capture_output=True, text=True)
			if res.returncode == 0:
				print("   [OK] Daemon regenerated and redpill-llm.service restarted.")
			else:
				print(f"   [WARN] Daemon regeneration failed: {res.stderr[-400:]}")
		else:
			print("   [SKIP] setup_background_model.sh or bash unavailable.")
	except Exception as e:
		print(f"   [WARN] Daemon regeneration skipped: {e}")

	print("2.8 Redeploying skills to the agent skills dir...")
	# Skills live in ./skills (canonical) and are deployed to ~/.agent/skills by
	# install_neo; mirror that here so `update` also refreshes them.
	try:
		skills_src = project_root / "skills"
		agent_dir = Path(os.getenv("RED_PILL_AGENT_DIR", str(Path.home() / ".agent")))
		skills_dest = agent_dir / "skills"
		if skills_src.is_dir():
			skills_dest.mkdir(parents=True, exist_ok=True)
			deployed = 0
			for skill in skills_src.iterdir():
				if skill.is_dir() and (skill / "SKILL.md").exists():
					dest = skills_dest / skill.name
					if dest.exists():
						shutil.rmtree(dest)
					shutil.copytree(skill, dest)
					deployed += 1
			print(f"   [OK] {deployed} skills redeployed to {skills_dest}.")
		else:
			print("   [SKIP] No skills directory found.")
	except Exception as e:
		print(f"   [WARN] Skills redeploy skipped: {e}")

	print("3. Running database migrations / checks...")
	try:
		import sys

		venv_python = project_root / ".venv" / "bin" / "python"
		if not venv_python.exists():
			venv_python = Path(sys.executable)

		migration_failed = False
		migration_errors = []
		for coll in ["work", "social", "directive", "story", "interaction"]:
			res = subprocess.run(
				[str(venv_python), "-m", "red_pill.cli", "sanitize", coll, "--dry-run"], cwd=str(project_root), capture_output=True, text=True
			)
			if res.returncode != 0:
				migration_failed = True
				migration_errors.append(f"{coll}: {res.stderr.strip()}")
		if not migration_failed:
			print("   [OK] Database structures checked and sanitized.")
		else:
			print("   [FAIL] Database sanitation check failed:\n" + "\n".join(migration_errors))
	except Exception as e:
		print(f"   [FAIL] Database migration exception: {e}")

	print("3.5 Refreshing PROTOCOL VERSION engram from CHANGELOG...")
	refresh_protocol_version_engram(project_root)

	if shutil.which("systemctl"):
		print("4. Reloading user systemd daemons...")
		try:
			res_running = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True)
			dbus_ok = res_running.returncode != 4
		except Exception:
			dbus_ok = False

		if dbus_ok:
			res = subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
			if res.returncode == 0:
				print("   [OK] User systemd services reloaded.")
			else:
				print(f"   [FAIL] systemd daemon-reload failed: {res.stderr}")
		else:
			print("   [INFO] systemd D-Bus init bus is unreachable. Skipping daemon-reload.")
	else:
		print("4. systemctl not found. Skipping daemon reload.")

	print("\n[OK] BÜNKER SYNCHRONIZATION CONCLUDED.")


def handle_bunker(args) -> None:
	"""Dispatcher for 'bunker' CLI commands."""
	if args.bunker_cmd == "init":
		profile_hardware()
	elif args.bunker_cmd == "install":
		bunker_install()
	elif args.bunker_cmd == "update":
		bunker_update()
	elif args.bunker_cmd == "export":
		bunker_export()
	elif args.bunker_cmd == "restore":
		bunker_restore(target_path=getattr(args, "source", None), kem_path=getattr(args, "kem", None), sig_path=getattr(args, "sig", None))
	elif args.bunker_cmd == "uninstall":
		bunker_uninstall()
	elif args.bunker_cmd == "export-keys":
		bunker_export_keys()
	else:
		print("[ERROR] Invalid bunker command.")


if __name__ == "__main__":
	# Standalone: refresh the PROTOCOL VERSION engram from the working tree's CHANGELOG
	refresh_protocol_version_engram(Path(__file__).parent.parent.parent)
