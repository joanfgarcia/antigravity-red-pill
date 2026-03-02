import logging
import os
import shutil
import tarfile
import time
from typing import Any, Dict, List, Optional

import requests  # type: ignore

import red_pill.config as cfg
from red_pill.utils.vault import CloudVault

logger = logging.getLogger(__name__)


class SoulManager:
	"""
	B760 Soul Management System.
	Handles backups, restoration, and portability of the AI's identity and memory.
	"""

	def __init__(self):
		self.ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
		self.backup_root = os.path.join(self.ia_dir, "backups")
		self.qdrant_url = cfg.QDRANT_URL
		self.api_key = cfg.QDRANT_API_KEY
		self.vault = CloudVault()

	def _get_collections(self) -> List[str]:
		"""Fetch all collection names from Qdrant."""
		try:
			headers = {"api-key": self.api_key} if self.api_key else {}
			resp = requests.get(f"{self.qdrant_url}/collections", headers=headers, timeout=5)
			resp.raise_for_status()
			collections_info: List[Dict[str, Any]] = resp.json()["result"]["collections"]
			return [c["name"] for c in collections_info]
		except Exception as e:
			logger.error(f"Failed to fetch collections: {e}")
			return []

	def backup_qdrant(self, timestamp: str) -> List[str]:
		"""Take snapshots of all Qdrant collections."""
		backup_dir = os.path.join(self.backup_root, "qdrant")
		os.makedirs(backup_dir, exist_ok=True)
		collections = self._get_collections()
		saved_files = []

		headers = {"api-key": self.api_key} if self.api_key else {}

		for coll in collections:
			try:
				logger.info(f"Taking snapshot for {coll}...")
				# 1. Create snapshot
				resp = requests.post(f"{self.qdrant_url}/collections/{coll}/snapshots", headers=headers, timeout=30)
				resp.raise_for_status()
				snap_name = resp.json()["result"]["name"]

				# 2. Download snapshot
				snap_path = os.path.join(backup_dir, f"{coll}_{timestamp}.snapshot")
				with requests.get(f"{self.qdrant_url}/collections/{coll}/snapshots/{snap_name}", headers=headers, stream=True) as r:
					r.raise_for_status()
					with open(snap_path, "wb") as f:
						shutil.copyfileobj(r.raw, f)

				saved_files.append(snap_path)
				logger.info(f"Saved: {snap_path}")
			except Exception as e:
				logger.error(f"Failed to backup collection {coll}: {e}")

		return saved_files

	def backup_files(self, timestamp: str) -> str:
		"""
		v5.6.1: Deprecated file-level backups (bloat risk).
		Replaced by Lean Manifesto (Manifest.json).
		"""
		logger.info("File-level recursive backup is deprecated. Using Lean Manifesto instead.")
		return ""

	def create_manifest(self, timestamp: str) -> str:
		"""Generate the 'Soul Manifesto' (Version metadata)."""
		import json

		from red_pill import __version__

		manifest = {
			"protocol_version": __version__,
			"schema_version": cfg.CURRENT_SCHEMA_VERSION,
			"embedding_model": cfg.EMBEDDING_MODEL,
			"vector_size": cfg.VECTOR_SIZE,
			"timestamp": timestamp,
			"hardware_context": "CUDA/ROCm/NPU-Ready",
		}
		manifest_path = os.path.join(self.backup_root, "qdrant", f"manifest_{timestamp}.json")
		with open(manifest_path, "w") as f:
			json.dump(manifest, f, indent="\t")
		return manifest_path

	def full_backup(self):
		"""Execute Lean Soul Backup (Snapshots + Manifesto)."""
		timestamp = time.strftime("%Y%m%d_%H%M%S")
		self.backup_qdrant(timestamp)
		self.create_manifest(timestamp)
		print(f"Lean Soul Backup completed at {timestamp}")

	def export_soul(self, output_path: Optional[str] = None):
		"""
		Export the 'Soul' (dynamic data) into a compact, encrypted kit.
		Following the Architect's 'Lean' directive (v5.6.1):
		Only Qdrant snapshots + Soul Manifesto.
		"""
		timestamp_full = time.strftime("%Y%m%d_%H%M%S")
		timestamp_short = time.strftime("%Y%m%d")

		# 1. Take snapshots and manifest using the same timestamp
		self.backup_qdrant(timestamp_full)
		self.create_manifest(timestamp_full)

		# 2. Package snapshots and manifest
		export_dir = os.path.join(self.ia_dir, "backups", "export")
		os.makedirs(export_dir, exist_ok=True)

		if not output_path:
			output_path = os.path.join(export_dir, f"LEAN_SOUL_KIT_{timestamp_short}.tar.gz")

		logger.info(f"Creating Lean Export Kit: {output_path}...")

		snapshot_dir = os.path.join(self.backup_root, "qdrant")

		# We only include the LATEST snapshots and the Manifesto from the current run
		with tarfile.open(output_path, "w:gz") as tar:
			manifest_file = f"manifest_{timestamp_full}.json"
			manifest_path = os.path.join(snapshot_dir, manifest_file)
			if os.path.exists(manifest_path):
				tar.add(manifest_path, arcname="manifest.json")

			for f in os.listdir(snapshot_dir):
				if f.endswith(".snapshot") and timestamp_full in f:
					f_path = os.path.join(snapshot_dir, f)
					tar.add(f_path, arcname=f"snapshots/{f}")

		print(f"Lean Export completed: {output_path} ({os.path.getsize(output_path) // 1024} KB)")

		# 3. Transmit to Cloud Vault if enabled
		if self.vault.enabled:
			file_id = self.vault.upload_kit(output_path)
			if file_id:
				print(f"Cloud Transmission Successful: {file_id}")
			else:
				print("Cloud Transmission Failed. Local kit preserved.")

		print("Note: Encryption (GPG) is enforced for Cloud Vault as per SEC-F02.")

	def restore_soul(self, source_dir: str, commit: bool = False):
		"""Restore soul files and Qdrant snapshots."""
		if not commit:
			print("DRY RUN: No files will be changed. Use --commit to execute.")

		# 1. Restore Files
		home_src = os.path.join(source_dir, "home")
		if os.path.exists(home_src):
			for root, dirs, files in os.walk(home_src):
				for file in files:
					src_file = os.path.join(root, file)
					rel_path = os.path.relpath(src_file, home_src)
					dest_file = os.path.join(os.path.expanduser("~"), rel_path)

					if commit:
						os.makedirs(os.path.dirname(dest_file), exist_ok=True)
						shutil.copy2(src_file, dest_file)
						logger.info(f"Restored: {dest_file}")
					else:
						print(f"Would restore: {dest_file}")

		# 2. Restore Qdrant (Optional: requires Qdrant to be up)
		# For snapshots, we'd need to upload them via API
		if commit:
			qdrant_backup_dir = os.path.join(self.backup_root, "qdrant")
			if os.path.exists(qdrant_backup_dir):
				headers = {"api-key": self.api_key} if self.api_key else {}
				for f in os.listdir(qdrant_backup_dir):
					if f.endswith(".snapshot"):
						coll = f.split("_")[0]  # Assumes convention coll_timestamp.snapshot
						snap_path = os.path.join(qdrant_backup_dir, f)
						try:
							logger.info(f"Restoring snapshot for {coll}...")
							with open(snap_path, "rb") as snap_file:
								upload_payload = {"snapshot": snap_file}
								resp = requests.post(
									f"{self.qdrant_url}/collections/{coll}/snapshots/upload",
									headers=headers,
									files=upload_payload,
									timeout=60,
								)
								resp.raise_for_status()
								logger.info(f"Successfully restored {coll}")
						except Exception as e:
							logger.error(f"Failed to restore {coll}: {e}")
