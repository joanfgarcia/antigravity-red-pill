import hashlib
import hmac
import logging
from typing import Optional, Tuple

from pure_mls.group import Welcome
from pure_mls.tree import KeyPackage

from red_pill.swarm.mls_manager import MLSManager

logger = logging.getLogger(__name__)


class MLSBridge:
	"""
	Thin bridge between SwarmMessagingSkill and MLSManager.
	Manages MLS group state per community and exposes a simple
	send/receive/join API.
	"""

	def __init__(self, shared_secret: bytes) -> None:
		self._manager = MLSManager()
		self._shared_secret = shared_secret

	# ------------------------------------------------------------------
	# Admission Token (HMAC guard)
	# ------------------------------------------------------------------

	def make_admission_token(self, key_package_bytes: bytes) -> str:
		"""Returns a base64-encoded HMAC-SHA256 of the KeyPackage bytes."""
		import base64

		mac = hmac.new(self._shared_secret, key_package_bytes, hashlib.sha256).digest()
		return base64.b64encode(mac).decode("utf-8")

	def verify_admission_token(self, key_package_bytes: bytes, token: str) -> bool:
		"""Returns True if the token is a valid HMAC for the given KeyPackage bytes."""

		try:
			expected = self.make_admission_token(key_package_bytes)
			return hmac.compare_digest(expected, token)
		except Exception as e:
			logger.warning(f"[MLSBridge] Token verification failed: {e}")
			return False

	# ------------------------------------------------------------------
	# Group management
	# ------------------------------------------------------------------

	def get_my_key_package(self) -> Tuple[bytes, str]:
		"""
		Returns (key_package_bytes, admission_token).
		Generates the KeyPackage from the current VaultCrypto identity.
		"""
		kp: KeyPackage = self._manager.get_key_package()
		kp_bytes = kp.to_bytes()
		token = self.make_admission_token(kp_bytes)
		return kp_bytes, token

	def has_group(self, community_alias: str) -> bool:
		return community_alias in self._manager.groups

	def process_welcome(self, community_alias: str, welcome_bytes: bytes) -> bool:
		"""
		Joins a community from a received Welcome message.
		Returns True on success.
		"""
		try:
			welcome = Welcome.from_bytes(welcome_bytes)
			self._manager.join_community(community_alias, welcome)
			logger.info(f"[MLSBridge] Joined community '{community_alias}' via Welcome.")
			return True
		except Exception as e:
			logger.error(f"[MLSBridge] Failed to process Welcome for '{community_alias}': {e}")
			return False

	def add_member_and_get_welcome(self, community_alias: str, target_kp_bytes: bytes) -> Optional[bytes]:
		"""
		Adds a new member to the group (or creates the group if it doesn't exist).
		Returns the Welcome bytes to be sent to the new member, or None on failure.
		"""
		try:
			kp = KeyPackage.from_bytes(target_kp_bytes)

			if not self.has_group(community_alias):
				logger.info(f"[MLSBridge] Creating new MLS group for '{community_alias}'.")
				self._manager.create_community(community_alias)

			group = self._manager.groups[community_alias]
			new_group, welcome, _ = group.add_member(kp)
			self._manager.groups[community_alias] = new_group
			self._manager.save_group(community_alias)

			return welcome.to_bytes()
		except Exception as e:
			logger.error(f"[MLSBridge] add_member failed for '{community_alias}': {e}")
			return None

	# ------------------------------------------------------------------
	# Encrypt / Decrypt
	# ------------------------------------------------------------------

	def encrypt(self, community_alias: str, plaintext: bytes) -> Optional[bytes]:
		"""Encrypts a message for the given community group."""
		try:
			return self._manager.encrypt(community_alias, plaintext)
		except Exception as e:
			logger.error(f"[MLSBridge] Encrypt failed for '{community_alias}': {e}")
			return None

	def decrypt(self, community_alias: str, ciphertext: bytes) -> Optional[bytes]:
		"""Decrypts a message from the given community group."""
		try:
			return self._manager.decrypt(community_alias, ciphertext)
		except Exception as e:
			logger.error(f"[MLSBridge] Decrypt failed for '{community_alias}': {e}")
			return None
