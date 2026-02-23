import logging
import os
import shutil
import tarfile
import time
from typing import List, Optional

import requests

import red_pill.config as cfg

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

	def _get_collections(self) -> List[str]:
		"""Fetch all collection names from Qdrant."""
		try:
			headers = {"api-key": self.api_key} if self.api_key else {}
			resp = requests.get(f"{self.qdrant_url}/collections", headers=headers, timeout=5)
			resp.raise_for_status()
			return [c["name"] for c in resp.json()["result"]["collections"]]
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
					with open(snap_path, 'wb') as f:
						shutil.copyfileobj(r.raw, f)

				saved_files.append(snap_path)
				logger.info(f"Saved: {snap_path}")
			except Exception as e:
				logger.error(f"Failed to backup collection {coll}: {e}")

		return saved_files

	def backup_files(self, timestamp: str) -> str:
		"""Backup identity and configuration files."""
		soul_backup_dir = os.path.join(self.backup_root, "soul", timestamp)
		os.makedirs(soul_backup_dir, exist_ok=True)

		files_to_backup = [
			os.path.expanduser("~/.gemini/GEMINI.md"),
			os.path.expanduser("~/.gemini/antigravity/rules/snapshot_rule.md"),
		]

		# Add skills and rules recursively
		dirs_to_backup = [
			os.path.expanduser("~/.gemini/antigravity/skills"),
			os.path.expanduser("~/.gemini/antigravity/rules"),
			os.path.expanduser("~/.agent/rules"), # Preserve any Minion specific rules.
		]

		copied_count = 0
		for file_path in files_to_backup:
			if os.path.exists(file_path):
				# Reconstruct path relative to HOME or root?
				# Let's simple-copy with a prefix for now, or use a flat structure with path info.
				# To match the restore logic, we'll mimic the home structure.
				rel_path = os.path.relpath(file_path, os.path.expanduser("~"))
				dest = os.path.join(soul_backup_dir, "home", rel_path)
				os.makedirs(os.path.dirname(dest), exist_ok=True)
				shutil.copy2(file_path, dest)
				copied_count += 1

		for dir_path in dirs_to_backup:
			if os.path.exists(dir_path):
				rel_path = os.path.relpath(dir_path, os.path.expanduser("~"))
				dest = os.path.join(soul_backup_dir, "home", rel_path)
				if os.path.exists(dest):
					shutil.rmtree(dest)
				shutil.copytree(dir_path, dest)
				copied_count += 1

		logger.info(f"Backup files completed: {copied_count} items backed up to {soul_backup_dir}")
		return soul_backup_dir

	def full_backup(self):
		"""Execute total soul backup (Qdrant + Files)."""
		timestamp = time.strftime("%Y%m%d_%H%M%S")
		self.backup_qdrant(timestamp)
		self.backup_files(timestamp)
		print(f"Total backup completed at {timestamp}")

	def export_soul(self, output_path: Optional[str] = None):
		"""Export the soul into a single encrypted/compressed kit."""
		timestamp = time.strftime("%Y%m%d")
		# 1. Perform a fresh backup first
		self.full_backup()

		# 2. Package everything in IA_DIR/backups and ~/.gemini/antigravity
		export_dir = os.path.join(self.ia_dir, "backups", "export")
		os.makedirs(export_dir, exist_ok=True)

		if not output_path:
			output_path = os.path.join(export_dir, f"SOUL_KIT_{timestamp}.tar.gz")

		logger.info(f"Creating export kit: {output_path}...")
		with tarfile.open(output_path, "w:gz") as tar:
			# Add IA_DIR content
			tar.add(self.ia_dir, arcname="IA_DATA")
			# Add .gemini antigravity config
			gemini_dir = os.path.expanduser("~/.gemini")
			if os.path.exists(gemini_dir):
				tar.add(gemini_dir, arcname="GEMINI_CONFIG")

		print(f"Export completed: {output_path}")
		print("Note: Encryption (GPG) should be handled by the operator for high-security environments.")

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
						coll = f.split("_")[0] # Assumes convention coll_timestamp.snapshot
						snap_path = os.path.join(qdrant_backup_dir, f)
						try:
							logger.info(f"Restoring snapshot for {coll}...")
							with open(snap_path, 'rb') as snap_file:
								files = {'snapshot': snap_file}
								resp = requests.post(
									f"{self.qdrant_url}/collections/{coll}/snapshots/upload",
									headers=headers,
									files=files,
									timeout=60
								)
								resp.raise_for_status()
								logger.info(f"Successfully restored {coll}")
						except Exception as e:
							logger.error(f"Failed to restore {coll}: {e}")
