import base64
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

import red_pill.config as cfg
from red_pill.core.paths import get_data_dir, get_queue_dir

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
			self.db_path = str(get_queue_dir() / "minion_inbox.db")
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
		mls_path = str(get_data_dir() / "swarm_groups" / "internal_minions.mls")
		os.makedirs(os.path.dirname(mls_path), exist_ok=True)

		# Admin identity
		sig_key = SignatureKey(private_key=ed25519.Ed25519PrivateKey.generate())
		try:
			from cryptography.hazmat.primitives.asymmetric import x25519

			kem_key = KemKey(private_key=x25519.X25519PrivateKey.generate())
		except ImportError:
			logger.warning("x25519 not found, generating dummy KemKey")
			kem_key = None  # will fail later if not defined, but we'll try to import x25519 properly

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
		with sqlite3.connect(self.db_path, timeout=30.0) as conn:
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
					originator TEXT,
					continuity_id TEXT
				)
				"""
			)
			cursor.execute("CREATE INDEX IF NOT EXISTS idx_is_read ON inbox (is_read)")
			try:
				cursor.execute("ALTER TABLE inbox ADD COLUMN originator TEXT")
			except sqlite3.OperationalError:
				pass
			try:
				cursor.execute("ALTER TABLE inbox ADD COLUMN continuity_id TEXT")
			except sqlite3.OperationalError:
				pass
			conn.commit()

	def drop_report(
		self,
		event_id: str,
		source: str,
		status: str,
		content: str,
		originator: Optional[str] = None,
		continuity_id: Optional[str] = None,
		*,
		notify: bool = True,
	) -> None:
		"""Save a fire-and-forget report from a background minion.

		D2 (idempotencia): el `event_id` es la clave de deduplicación. Si ya
		existe una fila con ese `event_id`, la llamada es un no-op — un reintento
		del minion o una doble entrega no duplican el informe. La comprobación no
		va en un SELECT aparte: vive dentro del propio `INSERT ... SELECT WHERE
		NOT EXISTS`, que SQLite serializa bajo el write-lock, así que tampoco hay
		carrera entre dos minions que lleguen con el mismo id. Con `event_id`
		vacío no hay nada que deduplicar, así que se inserta (comportamiento
		histórico).
		"""
		raw_content = content
		if cfg.ICE_MODE_ENABLED and self.mls_group is not None:
			try:
				msg_bytes = self.mls_group.encrypt_application_message(content.encode("utf-8"))
				content = base64.b64encode(msg_bytes).decode("utf-8")
			except Exception as e:
				logger.error(f"ICE encryption failed in drop_report: {e}")
				return

		inserted = False
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				cursor = conn.cursor()
				columns = "event_id, source, status, content, timestamp, originator, continuity_id"
				values = (event_id, source, status, content, time.time(), originator, continuity_id)
				if event_id:
					# D2: la deduplicación VA EN la misma sentencia de escritura
					# (no en un SELECT previo), que es lo único que SQLite
					# serializa bajo el write-lock frente a otro minion simultáneo.
					cursor.execute(
						f"INSERT INTO inbox ({columns}) SELECT ?, ?, ?, ?, ?, ?, ? "
						"WHERE NOT EXISTS (SELECT 1 FROM inbox WHERE event_id = ?)",
						values + (event_id,),
					)
					if cursor.rowcount == 0:
						logger.debug(f"drop_report D2: event_id {event_id} ya registrado; no se duplica.")
					else:
						inserted = True
				else:
					cursor.execute(f"INSERT INTO inbox ({columns}) VALUES (?, ?, ?, ?, ?, ?, ?)", values)
					inserted = True
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to drop report in MinionInbox: {e}")
			return

		# Un reporte con alma despierta a su dueña por el coro (S2.1+). El JobRunner
		# ya lo hace en `_report_job` con el aviso completo; los demás minions llegan
		# aquí. Best-effort: un fallo del aviso no tumba al minion.
		if (
			inserted
			and notify
			and continuity_id
			and source != "JobRunner"
			and os.getenv("REDPILL_INBOX_NOTIFY_DISABLE") != "1"
		):
			try:
				from red_pill.coro.notify import publish_notice

				publish_notice(
					continuity_id=str(continuity_id),
					body=f"[MinionInbox] {source} · {status}: {raw_content[:600]}",
					originator=originator or f"minion:{source}",
				)
			except Exception as e:
				logger.debug(f"[inbox] aviso coro no publicado: {e}")

	def get_unread(self, limit: int = 50) -> List[Dict[str, Any]]:
		"""Retrieve unread reports WITHOUT marking them as read (non-destructive peek)."""
		reports: List[Dict[str, Any]] = []
		rows = []
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute(
					"SELECT id, event_id, source, status, content, is_read, timestamp, originator, continuity_id "
					"FROM inbox WHERE is_read = 0 ORDER BY timestamp DESC LIMIT ?",
					(limit,),
				)
				db_rows = cursor.fetchall()
				rows = [dict(row) for row in db_rows]
		except Exception as e:
			logger.error(f"Failed to get unread reports: {e}")
			return []

		for d in rows:
			if cfg.ICE_MODE_ENABLED and self.mls_group is not None:
				try:
					raw_bytes = base64.b64decode(d["content"])
					d["content"] = self.mls_group.decrypt_application_message(raw_bytes).decode("utf-8")
				except Exception as e:
					logger.error(f"ICE decryption failed for report {d['id']}: {e}")
					d["content"] = "<ICE Decryption Failed>"
			reports.append(d)
		return reports

	def resolve_report(self, event_id: str) -> int:
		"""Entierra un reporte por su `event_id` (contrapartida de `drop_report`).

		Las señales silenciadas (`inject_signal(muted=True)`) no viven en Qdrant,
		así que `evaporate_signals` no las alcanza: su entierro es cerrar el
		reporte. Sin esto, un dolor silenciado se queda en el buzón para siempre
		aunque la causa haya desaparecido (medido 2026-11-12: `memento_stale_
		distill` seguía vivo después de que la noche destilara las 16 sesiones).

		Idempotente y no destructivo: marca leídas las filas de ese `event_id`
		(el histórico queda para auditoría; `purge_read` lo retira después).
		Devuelve cuántas filas cerró.
		"""
		if not event_id:
			return 0
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				cursor = conn.cursor()
				cursor.execute("UPDATE inbox SET is_read = 1 WHERE event_id = ? AND is_read = 0", (event_id,))
				resolved = cursor.rowcount or 0
				conn.commit()
			if resolved:
				logger.info(f"[Inbox] reporte '{event_id}' enterrado ({resolved} fila/s).")
			return resolved
		except Exception as e:
			logger.warning(f"[Inbox] no se pudo enterrar el reporte '{event_id}': {e}")
			return 0

	def mark_as_read(self, report_ids: List[int]) -> None:
		"""Mark specific reports as read by ID."""
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				cursor = conn.cursor()
				placeholders = ",".join("?" * len(report_ids))
				cursor.execute(f"UPDATE inbox SET is_read = 1 WHERE id IN ({placeholders})", report_ids)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to mark reports as read: {e}")

	def pop_unread(self, limit: int = 50) -> List[Dict[str, Any]]:
		"""Retrieve unread reports and mark them as read atomically."""
		reports: List[Dict[str, Any]] = []
		rows = []
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				# Fetch inside transaction
				cursor.execute(
					"SELECT id, event_id, source, status, content, is_read, timestamp, originator, continuity_id "
					"FROM inbox WHERE is_read = 0 ORDER BY timestamp DESC LIMIT ?",
					(limit,),
				)
				db_rows = cursor.fetchall()
				rows = [dict(row) for row in db_rows]
				if rows:
					report_ids = [row["id"] for row in rows]
					placeholders = ",".join("?" * len(report_ids))
					cursor.execute(f"UPDATE inbox SET is_read = 1 WHERE id IN ({placeholders})", report_ids)
				conn.commit()
		except Exception as e:
			logger.error(f"Failed to pop unread reports: {e}")
			return []

		for d in rows:
			if cfg.ICE_MODE_ENABLED and self.mls_group is not None:
				try:
					raw_bytes = base64.b64decode(d["content"])
					d["content"] = self.mls_group.decrypt_application_message(raw_bytes).decode("utf-8")
				except Exception as e:
					logger.error(f"ICE decryption failed for report {d['id']}: {e}")
					d["content"] = "<ICE Decryption Failed>"
			reports.append(d)
		return reports

	def purge_read(self) -> None:
		"""Delete all read messages to keep the inbox completely sterile."""
		try:
			with sqlite3.connect(self.db_path, timeout=30.0) as conn:
				cursor = conn.cursor()
				cursor.execute("DELETE FROM inbox WHERE is_read = 1")
				deleted = cursor.rowcount
				conn.commit()
				if deleted > 0:
					logger.debug(f"Purged {deleted} obsolete reports from MinionInbox.")
		except Exception as e:
			logger.error(f"Failed to purge MinionInbox: {e}")
