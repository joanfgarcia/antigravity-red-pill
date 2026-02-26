"""
SEC-001: Recovery Hash Keystore
================================
Stores the Argon2-id recovery hash in an OS-level file (~/.config/red_pill/recovery.key)
with strict mode-600 permissions, completely outside of Qdrant.

This replaces the previous approach of storing master_hash as a Qdrant payload,
which exposed the hash to anyone with read access to the vector database.

Architecture:
- WRITE  -> keystore.store_recovery_hash(hash)  -> ~/.config/red_pill/recovery.key (mode 600)
- READ   -> keystore.load_recovery_hash()        -> str | None
- CHECK  -> keystore.has_recovery_hash()         -> bool
- DELETE -> keystore.delete_recovery_hash()      -> None  (Scorched Earth support)

Qdrant stores ONLY a boolean marker: {"irp_active": True} -- no hash, no password material.
"""
import logging
import os
import stat
from typing import Optional

logger = logging.getLogger(__name__)

# Default path; can be overridden via env var for testing.
_DEFAULT_KEYSTORE_DIR = os.path.expanduser("~/.config/red_pill")
_DEFAULT_KEYSTORE_FILE = "recovery.key"

KEYSTORE_DIR = os.getenv("RED_PILL_KEYSTORE_DIR", _DEFAULT_KEYSTORE_DIR)
KEYSTORE_PATH = os.path.join(KEYSTORE_DIR, _DEFAULT_KEYSTORE_FILE)


def _ensure_dir() -> None:
	"""Creates the keystore directory with strict permissions (mode 700)."""
	os.makedirs(KEYSTORE_DIR, mode=0o700, exist_ok=True)
	# Enforce mode even if directory already existed.
	os.chmod(KEYSTORE_DIR, 0o700)


def store_recovery_hash(argon2_hash: str) -> None:
	"""
	Persists the Argon2-id hash to the OS-level keystore file.

	The file is written atomically (via a temp file + rename) to prevent
	torn writes in concurrent scenarios (CQ-004 pattern applied here too).

	File permissions are enforced at 600 (owner read/write only).

	Args:
		argon2_hash: The full Argon2-id hash string (e.g. $argon2id$v=19$...).

	Raises:
		ValueError: If argon2_hash is empty or does not look like an Argon2 hash.
		OSError: If the file cannot be written (permissions, disk full, etc.).
	"""
	if not argon2_hash or not argon2_hash.startswith("$argon2"):
		raise ValueError(
			"Invalid Argon2 hash: must be a non-empty string starting with '$argon2'. "
			"Do NOT pass a raw SHA-256 hex digest or plaintext password."
		)

	_ensure_dir()

	# Atomic write: write to temp → rename (POSIX rename is atomic)
	tmp_path = KEYSTORE_PATH + ".tmp"
	try:
		# Open with O_WRONLY | O_CREAT | O_TRUNC | O_EXCL-like flags via mode
		fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
		with os.fdopen(fd, "w") as f:
			f.write(argon2_hash.strip())
		os.chmod(tmp_path, 0o600)
		os.replace(tmp_path, KEYSTORE_PATH)
		logger.info("SEC-001: Recovery hash stored in OS keystore (mode 600).")
	except Exception:
		# Clean up temp file on failure
		try:
			os.unlink(tmp_path)
		except OSError:
			pass
		raise


def load_recovery_hash() -> Optional[str]:
	"""
	Reads the Argon2-id hash from the keystore file.

	Returns:
		The hash string, or None if no keystore file exists.

	Raises:
		PermissionError: If the keystore file has insecure permissions (> 600).
		OSError: If the file exists but cannot be read.
	"""
	if not os.path.exists(KEYSTORE_PATH):
		return None

	# Enforce mode: reject if world- or group-readable
	file_stat = os.stat(KEYSTORE_PATH)
	if file_stat.st_mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
		raise PermissionError(
			f"SEC-001: Keystore file {KEYSTORE_PATH!r} has insecure permissions "
			f"({oct(file_stat.st_mode)}). Expected mode 600. "
			"Run: chmod 600 ~/.config/red_pill/recovery.key"
		)

	with open(KEYSTORE_PATH, "r") as f:
		value = f.read().strip()

	return value if value else None


def has_recovery_hash() -> bool:
	"""Returns True if a recovery hash file exists and is non-empty."""
	try:
		return load_recovery_hash() is not None
	except (PermissionError, OSError):
		return False


def delete_recovery_hash() -> None:
	"""
	Securely removes the keystore file (Scorched Earth support).
	Silently succeeds if the file does not exist.
	"""
	try:
		os.unlink(KEYSTORE_PATH)
		logger.info("SEC-001: Recovery keystore deleted (Scorched Earth).")
	except FileNotFoundError:
		pass
	except OSError as e:
		logger.error(f"SEC-001: Failed to delete keystore: {e}")
		raise
