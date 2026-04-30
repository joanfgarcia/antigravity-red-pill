import base64
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

import red_pill.config as cfg

try:
    import cryptography.hazmat.primitives.asymmetric.ed25519 as ed25519
    from pure_mls.group import MLSGroup
    HAS_PURE_MLS = True
    from pure_mls.keys import KemKey, SignatureKey
except ImportError:
    HAS_PURE_MLS = False

logger = logging.getLogger(__name__)


class MinionInbox:
	"""
	Lightweight SQLite Inbox for background swarm operations.
	Completely bypasses Qdrant to avoid vectorizing ephemeral JSON/text reports.
	"""

	def __init__(self, db_path: Optional[str] = None):
		if db_path is None:
			# Sovereign Pod path inside sharing storage repository
			self.db_path = os.path.join(cfg._IA_DIR, "storage", "queue", "minion_inbox.db")
		else:
			self.db_path = db_path

		# Ensure the directory exists
		os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
		self._init_db()

		self.mls_group: Optional["MLSGroup"] = None
		if cfg.ICE_MODE_ENABLED and HAS_PURE_MLS:
			self._init_mls_group()

	def _init_mls_group(self):
		group_id = b"internal_minions"
		mls_path = os.path.join(cfg._IA_DIR, "storage", "swarm_groups", "internal_minions.mls")
		os.makedirs(os.path.dirname(mls_path), exist_ok=True)

		# Admin identity
		sig_key = SignatureKey(private_key=ed25519.Ed25519PrivateKey.generate())
		try:
			from cryptography.hazmat.primitives.asymmetric import x25519
			kem_key = KemKey(private_key=x25519.X25519PrivateKey.generate())
		except ImportError:
			logger.warning("x25519 not found, generating dummy KemKey")
			kem_key = None # will fail later if not defined, but we'll try to import x25519 properly

		if os.path.exists(mls_path):
			try:
				with open(mls_path, "rb") as f:
					state = f.read()
				self.mls_group = MLSGroup.from_bytes(state)
			except Exception as e:
				logger.warning(f"Failed to load ICE MLS state: {e}. Recreating...")
				if kem_key:
					self.mls_group = MLSGroup.create(group_id, sig_key, kem_key)
				with open(mls_path, "wb") as f:
					if self.mls_group:
						f.write(self.mls_group.to_bytes())
		else:
			if kem_key:
				self.mls_group = MLSGroup.create(group_id, sig_key, kem_key)
			with open(mls_path, "wb") as f:
				if self.mls_group:
					f.write(self.mls_group.to_bytes())

	def _init_db(self) -> None:
		with sqlite3.connect(self.db_path) as conn:
			cursor = conn.cursor()
			# Enable Write-Ahead Logging for graceful concurrency across minions
			cursor.execute("PRAGMA journal_mode=WAL;")
			cursor.execute("PRAGMA synchronous=NORMAL;")
			cursor.execute(
				"""
				CREATE TABLE IF NOT EXISTS inbox (
					id INTEGER PRIMARY KEY AUTOINCREMENT,
					event_id TEXT,
					source TEXT,
					status TEXT,
					content TEXT,
					is_read INTEGER DEFAULT 0,
					timestamp REAL,
					originator TEXT
				)
				"""
			)
			cursor.execute("CREATE INDEX IF NOT EXISTS idx_is_read ON inbox (is_read)")
			try:
				cursor.execute("ALTER TABLE inbox ADD COLUMN originator TEXT")
			except sqlite3.OperationalError:
				pass
			conn.commit()

	def drop_report(self, event_id: str, source: str, status: str, content: str, originator: Optional[str] = None) -> None:
		"""Save a fire-and-forget report from a background minion."""
		if cfg.ICE_MODE_ENABLED and self.mls_group is not None:
			try:
				msg_bytes = self.mls_group.encrypt_application_message(content.encode("utf-8"))
				content = base64.b64encode(msg_bytes).decode("utf-8")
			except Exception as e:
				logger.error(f"ICE encryption failed in drop_report: {e}")
				return

		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute(
					"INSERT INTO inbox (event_id, source, status, content, timestamp, originator) VALUES (?, ?, ?, ?, ?, ?)",
					(event_id, source, status, content, time.time(), originator),
				)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to drop report in MinionInbox: {e}")

	def get_unread(self, limit: int = 50) -> List[Dict[str, Any]]:
		"""Retrieve unread reports WITHOUT marking them as read (non-destructive peek)."""
		reports: List[Dict[str, Any]] = []
		try:
			with sqlite3.connect(self.db_path) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute(
					"SELECT id, event_id, source, status, content, is_read, timestamp, originator FROM inbox WHERE is_read = 0 ORDER BY timestamp DESC LIMIT ?",
					(limit,),
				)
				rows = cursor.fetchall()
				reports = []
				for row in rows:
					d = dict(row)
					if cfg.ICE_MODE_ENABLED and self.mls_group is not None:
						try:
							raw_bytes = base64.b64decode(d["content"])
							d["content"] = self.mls_group.decrypt_application_message(raw_bytes).decode("utf-8")
						except Exception as e:
							logger.error(f"ICE decryption failed for report {d['id']}: {e}")
							d["content"] = "<ICE Decryption Failed>"
					reports.append(d)
		except Exception as e:
			logger.error(f"Failed to get unread reports: {e}")
		return reports

	def mark_as_read(self, report_ids: List[int]) -> None:
		"""Mark specific reports as read by ID."""
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				placeholders = ",".join("?" * len(report_ids))
				cursor.execute(f"UPDATE inbox SET is_read = 1 WHERE id IN ({placeholders})", report_ids)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to mark reports as read: {e}")

	def pop_unread(self, limit: int = 50) -> List[Dict[str, Any]]:
		"""Retrieve unread reports and mark them as read atomically."""
		reports: List[Dict[str, Any]] = []
		try:
			with sqlite3.connect(self.db_path) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				# Fetch inside transaction
				cursor.execute(
					"SELECT id, event_id, source, status, content, is_read, timestamp, originator FROM inbox WHERE is_read = 0 ORDER BY timestamp DESC LIMIT ?",
					(limit,),
				)
				rows = cursor.fetchall()
				if rows:
					report_ids = [row["id"] for row in rows]
					placeholders = ",".join("?" * len(report_ids))
					cursor.execute(f"UPDATE inbox SET is_read = 1 WHERE id IN ({placeholders})", report_ids)
					reports = []
				for row in rows:
					d = dict(row)
					if cfg.ICE_MODE_ENABLED and self.mls_group is not None:
						try:
							raw_bytes = base64.b64decode(d["content"])
							d["content"] = self.mls_group.decrypt_application_message(raw_bytes).decode("utf-8")
						except Exception as e:
							logger.error(f"ICE decryption failed for report {d['id']}: {e}")
							d["content"] = "<ICE Decryption Failed>"
					reports.append(d)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to pop unread reports: {e}")
		return reports

	def purge_read(self) -> None:
		"""Delete all read messages to keep the inbox completely sterile."""
		try:
			with sqlite3.connect(self.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute("DELETE FROM inbox WHERE is_read = 1")
				deleted = cursor.rowcount
				conn.commit()
				if deleted > 0:
					logger.debug(f"Purged {deleted} obsolete reports from MinionInbox.")
		except Exception as e:
			logger.error(f"Failed to purge MinionInbox: {e}")
