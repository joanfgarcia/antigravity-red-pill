import logging
import os
import stat
from typing import Tuple

from pure_mls.keys import KemKey, SignatureKey

from red_pill.core.paths import get_config_dir

logger = logging.getLogger(__name__)

# SEC-001: Vault Seed Keystore
_DEFAULT_KEYSTORE_DIR = str(get_config_dir())
_DEFAULT_SEED_FILE = "vault.seed"

KEYSTORE_DIR = os.getenv("RED_PILL_KEYSTORE_DIR", _DEFAULT_KEYSTORE_DIR)
SEED_PATH = os.path.join(KEYSTORE_DIR, _DEFAULT_SEED_FILE)


class VaultCrypto:
	"""
	Sovereign Vault Cryptography (v1.0).
	Manages the persistent MLS identity for the Cloud Vault.
	"""

	@staticmethod
	def _ensure_dir():
		os.makedirs(KEYSTORE_DIR, mode=0o700, exist_ok=True)
		os.chmod(KEYSTORE_DIR, 0o700)

	@staticmethod
	def get_identity() -> Tuple[KemKey, SignatureKey]:
		"""
		Retrieves or generates the persistent vault identity.
		Returns a (KemKey, SignatureKey) pair.
		"""
		if os.path.exists(SEED_PATH):
			# Enforce mode 600
			file_stat = os.stat(SEED_PATH)
			if file_stat.st_mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
				logger.warning(f"SEC-001: Vault seed {SEED_PATH} has insecure permissions. Fixing to 600.")
				os.chmod(SEED_PATH, 0o600)

			with open(SEED_PATH, "rb") as f:
				seed = f.read(32)
		else:
			logger.info("SEC-001: Generating new Sovereign Vault Seed...")
			seed = os.urandom(32)
			VaultCrypto._ensure_dir()

			# Atomic write
			tmp_path = SEED_PATH + ".tmp"
			fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
			with os.fdopen(fd, "wb") as f:
				f.write(seed)
				f.flush()
				os.fsync(f.fileno())
			os.replace(tmp_path, SEED_PATH)
			logger.info(f"SEC-001: Vault identity seed secured at {SEED_PATH}")

		# Initialize pure-mls keys from the 32-byte seed
		kem_key = KemKey.from_private_bytes(seed)
		sig_key = SignatureKey.from_private_bytes(seed)
		return kem_key, sig_key
