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
			if coll == "specs_memories":
				logger.info(f"Skipping ghost collection: {coll} (Sovereign Rule: Zero-Bloat)")
				continue

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
		os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
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

		# 3. Handle Encryption & Transmission (SEC-F02)
		if self.vault.enabled or os.getenv("CLOUD_VAULT_GPG_PASSPHRASE"):
			encrypted_path = self.vault._encrypt_kit(output_path)
			if encrypted_path:
				# Replace original with encrypted version for local persistence
				os.remove(output_path)
				output_path = encrypted_path
				print(f"Lean Export Secured (AES-256): {output_path}")

		if self.vault.enabled:
			file_id = self.vault.upload_kit(output_path)
			if file_id:
				print(f"Cloud Transmission Successful: {file_id}")
			else:
				print("Cloud Transmission Failed. Local kit preserved.")

		print("Note: Encryption (GPG) is enforced for Cloud Vault as per SEC-F02.")

	def restore_soul(self, source_dir: str, commit: bool = False):
		"""
		Phase O.9: Perfect Recovery Protocol (v6.0).
		Restores engrams from an extracted Soul Kit or backup directory.
		"""
		if not commit:
			logger.info("DRY RUN: No changes will be applied. Use --commit to execute.")

		# 1. Look for snapshots in the provided source
		# Kits extracted often have a 'snapshots/' subfolder
		snapshot_candidates = []
		search_paths = [source_dir, os.path.join(source_dir, "snapshots")]

		for path in search_paths:
			if os.path.exists(path):
				for f in os.listdir(path):
					if f.endswith(".snapshot"):
						snapshot_candidates.append(os.path.join(path, f))

		if not snapshot_candidates:
			logger.error(f"No snapshots found in {source_dir}")
			return

		# 2. Process Snapshots
		headers = {"api-key": self.api_key} if self.api_key else {}
		for snap_path in snapshot_candidates:
			filename = os.path.basename(snap_path)
			collection = filename.split("_")[0]  # Assumes convention: collection_timestamp.snapshot

			if not commit:
				print(f"Would restore collection '{collection}' from {filename}")
				continue

			try:
				logger.info(f"Restoring '{collection}'...")
				# Ensure collection exists (with dummy params, snapshot will override)
				# Actually Qdrant snapshot upload often handles this, but explicit is safer
				try:
					requests.post(
						f"{self.qdrant_url}/collections/{collection}",
						headers=headers,
						json={"vectors": {"size": cfg.VECTOR_SIZE, "distance": "Cosine"}},
						timeout=5,
					)
				except Exception:
					pass

				with open(snap_path, "rb") as snap_file:
					resp = requests.post(
						f"{self.qdrant_url}/collections/{collection}/snapshots/upload",
						headers=headers,
						files={"snapshot": snap_file},
						timeout=300,  # Large snapshots need time
					)
					resp.raise_for_status()
					logger.info(f"[OK] Collection '{collection}' restored successfully.")
			except Exception as e:
				logger.error(f"[FAIL] Could not restore {collection}: {e}")

		if commit:
			print(f"\n[PROTOCOL COMPLETE] {len(snapshot_candidates)} collections processed. Soul Integrity synchronized.")
