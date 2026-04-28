import logging
import os
from typing import Dict

from pure_mls.group import GroupUpdate, MLSGroup, Welcome
from pure_mls.tree import KeyPackage

from red_pill.utils.vault_crypto import VaultCrypto

logger = logging.getLogger(__name__)

# SEC-001: Swarm State Directory
SWARM_STATE_DIR = os.path.join(os.path.expanduser("~/.config/red_pill"), "swarm_groups")


class MLSManager:
	"""
	Orchestrator for MLS groups in the Red-Pill Swarm.
	Each 'Community' (alias) corresponds to a unique MLS Group.
	"""

	def __init__(self):
		os.makedirs(SWARM_STATE_DIR, exist_ok=True)
		self.kem_key, self.sig_key = VaultCrypto.get_identity()
		self.groups: Dict[str, MLSGroup] = {}
		self._load_all_groups()

	def _get_group_path(self, alias: str) -> str:
		return os.path.join(SWARM_STATE_DIR, f"{alias}.mls")

	def _load_all_groups(self):
		"""Loads existing group states from disk."""
		for filename in os.listdir(SWARM_STATE_DIR):
			if filename.endswith(".mls"):
				alias = filename[:-4]
				path = os.path.join(SWARM_STATE_DIR, filename)
				try:
					with open(path, "rb") as f:
						data = f.read()
					group = MLSGroup.from_bytes(data)
					# Re-bind keys
					group.my_kem_key = self.kem_key
					group.my_sig_key = self.sig_key
					self.groups[alias] = group
				except Exception as e:
					logger.error(f"Failed to load swarm group {alias}: {e}")

	def save_group(self, alias: str):
		"""Persists a group state to disk."""
		if alias in self.groups:
			path = self._get_group_path(alias)
			with open(path, "wb") as f:
				f.write(self.groups[alias].to_bytes())

	def create_community(self, alias: str) -> MLSGroup:
		"""Initializes a new MLS group for a community."""
		logger.info(f"Creating new Swarm Community: {alias}")
		group = MLSGroup.create(alias.encode(), self.sig_key, self.kem_key)
		self.groups[alias] = group
		self.save_group(alias)
		return group

	def get_key_package(self) -> KeyPackage:
		"""Generates a KeyPackage for joining groups."""
		return KeyPackage.create(
			encryption_key=self.kem_key.public_bytes(),
			init_key_pub=self.kem_key.public_bytes(),
			signature_key=self.sig_key.public_bytes(),
			identity=self.sig_key.public_bytes(),
			sign_fn=self.sig_key.sign,
		)

	def join_community(self, alias: str, welcome: Welcome) -> MLSGroup:
		"""Joins a community using a Welcome message."""
		logger.info(f"Joining Swarm Community: {alias}")
		group = MLSGroup.join(welcome, self.sig_key, self.kem_key)
		self.groups[alias] = group
		self.save_group(alias)
		return group

	def process_update(self, alias: str, update: GroupUpdate):
		"""Processes a Commit/Update from a peer in the community."""
		if alias in self.groups:
			self.groups[alias] = self.groups[alias].process_update(update)
			self.save_group(alias)

	def encrypt(self, alias: str, plaintext: bytes) -> bytes:
		"""Encrypts a message for a specific community."""
		if alias not in self.groups:
			raise ValueError(f"Not a member of community: {alias}")
		return self.groups[alias].encrypt_application_message(plaintext)

	def decrypt(self, alias: str, ciphertext: bytes) -> bytes:
		"""Decrypts a message from a specific community."""
		if alias not in self.groups:
			raise ValueError(f"Not a member of community: {alias}")
		return self.groups[alias].decrypt_application_message(ciphertext)
